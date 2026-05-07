/*
Copyright 2026.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package controller

import (
	"context"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	logf "sigs.k8s.io/controller-runtime/pkg/log"

	agenttasksv1 "github.com/amit397/agentanvil/api/v1"
)

// AgentTaskReconciler reconciles a AgentTask object
type AgentTaskReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

// +kubebuilder:rbac:groups=agenttasks.agentanvil.com,resources=agenttasks,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=agenttasks.agentanvil.com,resources=agenttasks/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=agenttasks.agentanvil.com,resources=agenttasks/finalizers,verbs=update
// +kubebuilder:rbac:groups="",resources=pods,verbs=get;list;watch;create

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
// TODO(user): Modify the Reconcile function to compare the state specified by
// the AgentTask object against the actual cluster state, and then
// perform operations to make the cluster state reflect the state specified by
// the user.
//
// For more details, check Reconcile and its Result here:
// - https://pkg.go.dev/sigs.k8s.io/controller-runtime@v0.23.3/pkg/reconcile
func (r *AgentTaskReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := logf.FromContext(ctx)

	// TODO(user): your logic here
	logger.Info("Reconciling AgentTask")

	agenttask := &agenttasksv1.AgentTask{}

	// 1. Fetch the latest AgentTask from the API server.
	if err := r.Get(ctx, req.NamespacedName, agenttask); err != nil {
		// 2. If the object is not found, it might have been deleted after the reconcile request was queued. Return for now.
		// Will revisit if we need to handle finalization logic in the future.
		logger.Error(err, "Unable to fetch AgentTask")
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	// 2. If the object is being deleted, we can skip reconciliation
	if !agenttask.ObjectMeta.DeletionTimestamp.IsZero() {
		return ctrl.Result{}, nil
	}

	// 3. If the status is not initialized, set it to Pending
	if agenttask.Status.Phase == "" {
		agenttask.Status.Phase = agenttasksv1.Pending
		agenttask.Status.PodName = ""
		if err := r.Status().Update(ctx, agenttask); err != nil {
			logger.Error(err, "Unable to update AgentTask status to Pending")
			return ctrl.Result{}, err
		}
		logger.Info("Updated AgentTask status to Pending")

		return ctrl.Result{}, nil
	}

	// 4. Analyze the current state and decide what to do next based on if podName is set or not and the status phase.
	// If podName is not set, inspect the phase.
	if agenttask.Status.PodName == "" {
		// If phase is pending, we need to create a new pod for this task.
		if agenttask.Status.Phase == agenttasksv1.Pending {
			newPod := &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{
					GenerateName: agenttask.Name + "-pod-",
					Namespace:    agenttask.Namespace,
					Labels: map[string]string{
						"agenttask": agenttask.Name,
					},
				},
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{
						{
							Name:  "agent-task-container",
							Image: "busybox",                 // TODO: Replace with the actual image needed for the task
							Args:  []string{"sleep", "3600"}, // Placeholder command, replace with actual command for the task
						},
					},
					RestartPolicy: corev1.RestartPolicyNever,
				},
			}

			// Set the owner reference on the new Pod
			if err := controllerutil.SetControllerReference(agenttask, newPod, r.Scheme); err != nil {
				logger.Error(err, "Unable to set owner reference on new Pod")
				return ctrl.Result{}, err
			}

			if err := r.Create(ctx, newPod); err != nil {
				logger.Error(err, "Unable to create Pod for AgentTask")
				return ctrl.Result{}, err
			}

			logger.Info("Created new Pod for AgentTask", "podName", newPod.Name)

			// Update the AgentTask status with the new pod name and set phase to Provisioning
			agenttask.Status.PodName = newPod.Name
			agenttask.Status.Phase = agenttasksv1.Provisioning
			if err := r.Status().Update(ctx, agenttask); err != nil {
				logger.Error(err, "Unable to update AgentTask status with new Pod name")
				return ctrl.Result{}, err
			}

			logger.Info("Updated AgentTask status with new Pod name and set phase to Provisioning", "podName", newPod.Name)
		} else {
			// If PodName is not set but phase is not Pending, this is an invalid state. Log an error and update the status to Failed.
			// (We consider this invalid for now, may update in the future.)
			logger.Error(nil, "AgentTask is in unexpected state: PodName is empty but Phase is not Pending", "phase", agenttask.Status.Phase)

			agenttask.Status.Phase = agenttasksv1.Failed
			agenttask.Status.Reason = "Invalid state"
			if err := r.Status().Update(ctx, agenttask); err != nil {
				logger.Error(err, "Unable to update AgentTask status to Failed due to invalid state")
				return ctrl.Result{}, err
			}

			logger.Info("Updated AgentTask status to Failed due to invalid state")
		}
	} else {
		// If PodName is set, we can check the status of the pod and update the AgentTask status accordingly if needed.
		pod := &corev1.Pod{}
		err := r.Get(ctx, types.NamespacedName{Name: agenttask.Status.PodName, Namespace: agenttask.Namespace}, pod)

		if err != nil {
			if client.IgnoreNotFound(err) == nil && !(agenttask.Status.Phase == agenttasksv1.Completed || agenttask.Status.Phase == agenttasksv1.Failed || agenttask.Status.Phase == agenttasksv1.Evicted) {
				// If the pod is not found and the AgentTask status does not indicate a terminal phase, we consider this a failure and update the status to Failed.
				logger.Error(err, "Pod not found for AgentTask, marking as Failed", "podName", agenttask.Status.PodName)

				agenttask.Status.Phase = agenttasksv1.Failed
				agenttask.Status.Reason = "Pod not found"
				if err := r.Status().Update(ctx, agenttask); err != nil {
					logger.Error(err, "Unable to update AgentTask status to Failed due to missing Pod")
					return ctrl.Result{}, err
				}

				logger.Info("Updated AgentTask status to Failed due to missing Pod", "podName", agenttask.Status.PodName)
				return ctrl.Result{}, nil
			} else if client.IgnoreNotFound(err) == nil && (agenttask.Status.Phase == agenttasksv1.Completed || agenttask.Status.Phase == agenttasksv1.Failed || agenttask.Status.Phase == agenttasksv1.Evicted) {
				// If the pod is not found but the AgentTask status indicates a terminal phase, we ignore.
				logger.Info("Pod not found for AgentTask, but status is already in terminal phase, ignoring", "podName", agenttask.Status.PodName, "phase", agenttask.Status.Phase)
				return ctrl.Result{}, nil
			} else {
				// For any other error, log it and requeue.
				logger.Error(err, "Unable to fetch Pod for AgentTask", "podName", agenttask.Status.PodName)
				return ctrl.Result{}, err
			}
		}

		updateStatus := false
		switch pod.Status.Phase {
		case corev1.PodPending:
			if agenttask.Status.Phase != agenttasksv1.Provisioning {
				updateStatus = true
				logger.Info("Pod is pending, updating AgentTask status to Provisioning", "podName", pod.Name)
			}
			agenttask.Status.Phase = agenttasksv1.Provisioning
		case corev1.PodRunning:
			if agenttask.Status.Phase != agenttasksv1.Running {
				updateStatus = true
				logger.Info("Pod is running, updating AgentTask status to Running", "podName", pod.Name)
			}
			agenttask.Status.Phase = agenttasksv1.Running

			if agenttask.Status.StartedAt == nil {
				agenttask.Status.StartedAt = &metav1.Time{Time: metav1.Now().Time}
			}
		case corev1.PodSucceeded:
			if agenttask.Status.Phase != agenttasksv1.Completed {
				updateStatus = true
			}
			agenttask.Status.Phase = agenttasksv1.Completed
			logger.Info("Pod completed successfully, updating AgentTask status to Completed", "podName", pod.Name)

			if agenttask.Status.FinishedAt == nil {
				agenttask.Status.FinishedAt = &metav1.Time{Time: metav1.Now().Time}
			}
			agenttask.Status.Reason = "Pod completed successfully."
		case corev1.PodFailed:
			if pod.Status.Reason == "Evicted" {
				if agenttask.Status.Phase != agenttasksv1.Evicted {
					updateStatus = true
					logger.Info("Pod was evicted, updating AgentTask status to Evicted", "podName", pod.Name)
				}
				agenttask.Status.Phase = agenttasksv1.Evicted
				agenttask.Status.Reason = "Pod was evicted."
				if agenttask.Status.FinishedAt == nil {
					agenttask.Status.FinishedAt = &metav1.Time{Time: metav1.Now().Time}
				}
			} else {
				if agenttask.Status.Phase != agenttasksv1.Failed {
					updateStatus = true
					logger.Info("Pod failed, updating AgentTask status to Failed", "podName", pod.Name)
				}
				agenttask.Status.Phase = agenttasksv1.Failed
				agenttask.Status.Reason = "Pod failed."
			}
		default:
			logger.Error(nil, "Pod is in unexpected phase", "podPhase", pod.Status.Phase)
			agenttask.Status.Phase = agenttasksv1.Failed
			agenttask.Status.Reason = "Pod in unexpected phase"
			updateStatus = true
		}

		// Only update if there has been a change in status to avoid unnecessary API calls.
		if updateStatus {
			if err := r.Status().Update(ctx, agenttask); err != nil {
				logger.Error(err, "Unable to update AgentTask status based on Pod status", "podName", pod.Name)
				return ctrl.Result{}, err
			}
			logger.Info("Updated AgentTask status based on Pod status", "podName", pod.Name, "newPhase", agenttask.Status.Phase)
		}
	}

	return ctrl.Result{}, nil
}

// SetupWithManager sets up the controller with the Manager.
func (r *AgentTaskReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&agenttasksv1.AgentTask{}).
		Named("agenttask").
		Watches(
			&corev1.Pod{},
			handler.EnqueueRequestForOwner(mgr.GetScheme(), mgr.GetRESTMapper(), &agenttasksv1.AgentTask{}),
		).
		Complete(r)
}
