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
	"fmt"

	"crypto/sha256"

	logr "github.com/go-logr/logr"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	logf "sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/yaml"

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
// +kubebuilder:rbac:groups="",resources=configmaps,verbs=get;list;watch;create;update

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
			if err := r.ensureConfigMapForPod(ctx, agenttask, logger); err != nil {
				logger.Error(err, "Unable to ensure ConfigMap for Pod during initial Pending phase")
				return ctrl.Result{}, err
			}

			newPod := buildPodForAgentTask(agenttask)

			if newPod == nil {
				logger.Error(nil, "Unable to build Pod for AgentTask")
				return ctrl.Result{}, fmt.Errorf("unable to build Pod for AgentTask")
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
			agenttask.Status.FinishedAt = &metav1.Time{Time: metav1.Now().Time}
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
				agenttask.Status.FinishedAt = &metav1.Time{Time: metav1.Now().Time}
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

		if agenttask.Status.Phase == agenttasksv1.Running {
			configMap := pod.Spec.Volumes[0].VolumeSource.Projected.Sources[0].ConfigMap
			if configMap == nil {
				logger.Error(nil, "Error reading configMap for Pod", "podName", pod.Name)

				return ctrl.Result{}, fmt.Errorf("error reading configMap for Pod %s", pod.Name)
			}

			if configMap.Name != buildConfigMapName(agenttask) {
				logger.Info("AgentTask spec update ignored to preserve idempotenncy of running Pod", "podName", pod.Name, "currentConfigMap", configMap.Name, "expectedConfigMap", buildConfigMapName(agenttask))
			}
		}

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
				updateStatus = true

				agenttask.Status.StartedAt = &metav1.Time{Time: metav1.Now().Time}
				logger.Info("Set AgentTask StartedAt timestamp", "podName", pod.Name, "startedAt", agenttask.Status.StartedAt)
			}

		case corev1.PodSucceeded:
			if agenttask.Status.Phase != agenttasksv1.Completed {
				logger.Info("Pod completed successfully, updating AgentTask status to Completed", "podName", pod.Name)
				updateStatus = true
			}
			agenttask.Status.Phase = agenttasksv1.Completed

			if agenttask.Status.FinishedAt == nil {
				updateStatus = true
				agenttask.Status.FinishedAt = &metav1.Time{Time: metav1.Now().Time}
				logger.Info("Set AgentTask FinishedAt timestamp", "podName", pod.Name, "finishedAt", agenttask.Status.FinishedAt)
			}

			if agenttask.Status.Reason != "Pod completed successfully." {
				agenttask.Status.Reason = "Pod completed successfully."
				updateStatus = true
			}

		case corev1.PodFailed:
			if pod.Status.Reason == "Evicted" {
				if agenttask.Status.Phase != agenttasksv1.Evicted {
					updateStatus = true
					logger.Info("Pod was evicted, updating AgentTask status to Evicted", "podName", pod.Name)
				}
				agenttask.Status.Phase = agenttasksv1.Evicted

				if agenttask.Status.Reason != "Pod was evicted." {
					agenttask.Status.Reason = "Pod was evicted."
					updateStatus = true
				}
			} else {
				if agenttask.Status.Phase != agenttasksv1.Failed {
					updateStatus = true
					logger.Info("Pod failed, updating AgentTask status to Failed", "podName", pod.Name)
				}
				agenttask.Status.Phase = agenttasksv1.Failed

				if agenttask.Status.Reason != "Pod failed." {
					agenttask.Status.Reason = "Pod failed."
					updateStatus = true
				}
			}
			if agenttask.Status.FinishedAt == nil {
				updateStatus = true
				agenttask.Status.FinishedAt = &metav1.Time{Time: metav1.Now().Time}
				logger.Info("Set AgentTask FinishedAt timestamp", "podName", pod.Name, "finishedAt", agenttask.Status.FinishedAt)
			}

		default:
			logger.Error(nil, "Pod is in unexpected phase", "podPhase", pod.Status.Phase)
			agenttask.Status.Phase = agenttasksv1.Failed
			agenttask.Status.Reason = "Pod in unexpected phase"
			if agenttask.Status.FinishedAt == nil {
				agenttask.Status.FinishedAt = &metav1.Time{Time: metav1.Now().Time}
				updateStatus = true
			}

			if err := r.Status().Update(ctx, agenttask); err != nil {
				logger.Error(err, "Unable to update AgentTask status to Failed due to unexpected Pod phase")
				return ctrl.Result{}, err
			}

			logger.Info("Updated AgentTask status to Failed due to unexpected Pod phase", "podName", pod.Name, "podPhase", pod.Status.Phase)
			return ctrl.Result{}, nil
		}

		// Only update if there has been a change in status to avoid unnecessary API calls.
		if updateStatus {
			if err := r.Status().Update(ctx, agenttask); err != nil {
				logger.Error(err, "Unable to update AgentTask status based on Pod status", "podName", pod.Name)
				return ctrl.Result{}, err
			}
		}
	}

	return ctrl.Result{}, nil
}

// Helper function to build the ConfigMap for the Pod with the AgentTask spec data. This ConfigMap will be mounted as a volume in the Pod and used by the agent container to get the task configuration.
func buildConfigMapForAgentTask(agenttask *agenttasksv1.AgentTask, logger logr.Logger) *corev1.ConfigMap {
	if agenttask == nil {
		return nil
	}

	task_spec := agenttask.Spec

	yamlBytes, err := yaml.Marshal(task_spec)
	if err != nil {
		logger.Error(err, "Unable to marshal AgentTask spec to YAML for ConfigMap", "agentTaskName", agenttask.Name)
		return nil
	}

	config_map := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      buildConfigMapName(agenttask),
			Namespace: agenttask.Namespace,
		},
		Data: map[string]string{
			"task.yaml": string(yamlBytes),
		},
	}
	return config_map
}

// Helper function to hook ConfigMap to the Pod if not already present.
func (r *AgentTaskReconciler) ensureConfigMapForPod(ctx context.Context, agenttask *agenttasksv1.AgentTask, logger logr.Logger) error {
	if agenttask == nil {
		return nil
	}

	configMap := &corev1.ConfigMap{}
	configMapName := buildConfigMapName(agenttask)
	err := r.Get(ctx, types.NamespacedName{Name: configMapName, Namespace: agenttask.Namespace}, configMap)
	if err != nil {
		if client.IgnoreNotFound(err) == nil && agenttask.Status.PodName == "" {
			// ConfigMap does not exist or has been updated, create it/update it.
			logger.Info("Creating ConfigMap for AgentTask", "configMapName", configMapName)
			newConfigMap := buildConfigMapForAgentTask(agenttask, logger)
			if newConfigMap == nil {
				logger.Error(nil, "Unable to build ConfigMap for AgentTask", "agentTaskName", agenttask.Name)
				return nil
			}

			if err := ctrl.SetControllerReference(agenttask, newConfigMap, r.Scheme); err != nil {
				logger.Error(err, "Unable to set owner reference on ConfigMap for AgentTask", "agentTaskName", agenttask.Name)
				return err
			}

			if err := r.Create(ctx, newConfigMap); err != nil {
				logger.Error(err, "Unable to create ConfigMap for AgentTask", "agentTaskName", agenttask.Name)
				return err
			}

			logger.Info("Created ConfigMap for AgentTask", "configMapName", newConfigMap.Name)
		} else if agenttask.Status.PodName != "" {
			logger.Error(err, "Pod already exists for AgentTask, blocking update of ConfigMap to preserve idempotency", "agentTaskName", agenttask.Name)
			return err
		} else {
			logger.Error(err, "Unable to fetch ConfigMap for AgentTask", "configMapName", configMapName)
			return err
		}
	} else {
		logger.Info("ConfigMap already exists for AgentTask", "configMapName", configMapName)
	}

	return nil
}

// Calculate a hash of the AgentTask spec to use as an annotation on the Pod for change detection.
func calculateSpecHash(agenttask *agenttasksv1.AgentTask, specBytes []byte) string {
	if agenttask == nil {
		return ""
	}

	hash := sha256.Sum256(specBytes)
	return fmt.Sprintf("%x", hash)
}

func buildConfigMapName(agenttask *agenttasksv1.AgentTask) string {
	if agenttask == nil {
		return ""
	}

	specBytes, err := yaml.Marshal(agenttask.Spec)
	if err != nil {
		// Log the error and return a fallback name or handle it as needed
		return ""
	}

	return agenttask.Name + calculateSpecHash(agenttask, specBytes) + "-config"
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
