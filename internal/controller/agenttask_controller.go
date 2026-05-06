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
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
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

	// 3. If the object is being deleted, we can skip reconciliation
	if !agenttask.ObjectMeta.DeletionTimestamp.IsZero() {
		return ctrl.Result{}, nil
	}

	// 4. Fetch the child resources (e.g., Pods) associated with this AgentTask and update status accordingly.
	// For now, we are only fetching Pods, and just one Pod. In the future, we may want to fetch other child resources like Services, ConfigMaps, etc. or more Pods depending on the needs of the AgentTask.
	podList := &corev1.PodList{}
	if err := r.List(ctx, podList, client.InNamespace(req.Namespace), client.MatchingLabels{"agenttask": req.Name}); err != nil {
		logger.Error(err, "Unable to list Pods for AgentTask")
		return ctrl.Result{}, err
	}

	// If there are no pods, create a new child pod, set its owner reference to the AgentTask, and update the status to reflect that the task is pending.
	if len(podList.Items) == 0 {
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

		if err := controllerutil.SetControllerReference(agenttask, newPod, r.Scheme); err != nil {
			logger.Error(err, "Unable to set owner reference on new Pod")
			return ctrl.Result{}, err
		}

		if err := r.Create(ctx, newPod); err != nil {
			logger.Error(err, "Unable to create child Pod for AgentTask")
			return ctrl.Result{}, err
		}

		if agenttask.Status.Phase == "" || agenttask.Status.Phase == "Pending" {
			agenttask.Status.Phase = agenttasksv1.Provisioning
			agenttask.Status.CurrentStep = 0
			agenttask.Status.StartedAt = nil
			agenttask.Status.FinishedAt = nil
			agenttask.Status.PodName = newPod.Name
			if err := r.Status().Update(ctx, agenttask); err != nil {
				logger.Error(err, "Unable to update AgentTask status to Provisioning")
				return ctrl.Result{}, err
			}
			logger.Info("Created child Pod and updated AgentTask status to Provisioning")
		}

	} else {
		// If there are pods, check their status and update the AgentTask status accordingly.
		pod := podList.Items[0]
		updateStatus := false

		switch pod.Status.Phase {
		case corev1.PodPending:
			if agenttask.Status.Phase != agenttasksv1.Provisioning {
				updateStatus = true
			}
			agenttask.Status.Phase = agenttasksv1.Provisioning
		case corev1.PodRunning:
			if agenttask.Status.Phase != agenttasksv1.Running {
				agenttask.Status.CurrentStep = 1 // Placeholder, in a real implementation this would be determined based on the actual progress of the task
				agenttask.Status.StartedAt = &metav1.Time{Time: metav1.Now().Time}
				agenttask.Status.FinishedAt = nil
				agenttask.Status.Reason = ""

				updateStatus = true
			}
			agenttask.Status.Phase = agenttasksv1.Running
		case corev1.PodSucceeded:
			if agenttask.Status.Phase != agenttasksv1.Completed {
				agenttask.Status.CurrentStep = 2 // Placeholder, in a real implementation this would be determined based on the actual progress of the task
				if agenttask.Status.FinishedAt == nil {
					agenttask.Status.FinishedAt = &metav1.Time{Time: metav1.Now().Time}
				}
				agenttask.Status.PodName = pod.Name
				agenttask.Status.Reason = agenttask.Status.Reason + pod.Status.Reason

				updateStatus = true
			}
			agenttask.Status.Phase = agenttasksv1.Completed
		case corev1.PodFailed:
			if pod.Status.Reason == "Evicted" {
				if agenttask.Status.Phase != agenttasksv1.Evicted {
					updateStatus = true
				}
				agenttask.Status.Phase = agenttasksv1.Evicted
			} else {
				if agenttask.Status.Phase != agenttasksv1.Failed {
					updateStatus = true
				}
				agenttask.Status.Phase = agenttasksv1.Failed
			}

			agenttask.Status.CurrentStep = -1 // Placeholder, in a real implementation this would be determined based on the actual progress of the task
			if agenttask.Status.FinishedAt == nil {
				agenttask.Status.FinishedAt = &metav1.Time{Time: metav1.Now().Time}
			}
			agenttask.Status.PodName = pod.Name
			agenttask.Status.Reason = agenttask.Status.Reason + pod.Status.Reason
			// In a real implementation, we would also want to capture the logs from the failed pod and include them in the AgentTask status for better debugging.
			// This is a placeholder for that logic.
			// logs, err := r.getPodLogs(ctx, &pod)
			// if err != nil {
			// 	logger.Error(err, "Unable to fetch logs from failed Pod")
			// } else {
			// 	agenttask.Status.Reason = agenttask.Status.Reason + "\nPod Logs:\n" + logs
			// }
			// Note: Fetching logs from the pod can be done using the Kubernetes API, but it may require additional permissions and handling of log streaming. This is a non-trivial addition and should be implemented with care to avoid performance issues or excessive log fetching.

		default:
			logger.Error(nil, "Unknown Pod phase", "phase", pod.Status.Phase)
		}

		if updateStatus {
			if err := r.Status().Update(ctx, agenttask); err != nil {
				logger.Error(err, "Unable to update AgentTask status based on Pod status")
				return ctrl.Result{}, err
			}
			logger.Info("Updated AgentTask status based on Pod status", "podPhase", pod.Status.Phase)
		}
	}

	return ctrl.Result{}, nil
}

// SetupWithManager sets up the controller with the Manager.
func (r *AgentTaskReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&agenttasksv1.AgentTask{}).
		Named("agenttask").
		Complete(r)
}
