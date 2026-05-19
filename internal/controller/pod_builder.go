package controller

import (
	agenttasksv1 "github.com/amit397/agentanvil/api/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

func buildPodForAgentTask(agenttask *agenttasksv1.AgentTask) *corev1.Pod {
	if agenttask == nil {
		return nil
	}

	taskID := agenttask.Name + "/" + agenttask.Namespace
	runtimeClassName := "gvisor"

	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			GenerateName: agenttask.Name + "-pod-",
			Namespace:    agenttask.Namespace,
			Labels: map[string]string{
				"agenttask": agenttask.Name,
			},
		},
		Spec: corev1.PodSpec{
			RuntimeClassName: &runtimeClassName,
			Containers: []corev1.Container{
				{
					Name:    "agent",
					Image:   "busybox",                                                                  // TODO: Replace with the actual image needed for the task
					Command: []string{"/bin/sh", "-c"},                                                  // Placeholder command, replace with actual command for the task
					Args:    []string{"echo \"Pod running for AgentTask " + taskID + "\" && sleep 120"}, // Placeholder command, replace with actual command for the task
					VolumeMounts: []corev1.VolumeMount{
						{
							Name:      "task",
							MountPath: "/etc/agent-anvil/",
							ReadOnly:  true,
						},
						{
							Name:      "trace",
							MountPath: "/var/log/agent-anvil",
							ReadOnly:  false,
						},
						{
							Name:      "workspace",
							MountPath: "/workspace",
							ReadOnly:  false,
						},
					},
					Env: []corev1.EnvVar{
						{
							Name:  "AGENT_ANVIL_TASK_ID",
							Value: taskID,
						},
						{
							Name:  "AGENT_ANVIL_PROXY_URL",
							Value: "http://localhost:8080", // TODO: Replace with actual proxy URL if needed
						},
						{
							Name:  "AGENT_ANVIL_TRACE_DIR",
							Value: "/var/log/agent-anvil",
						},
						{
							Name:  "AGENT_ANVIL_WORKSPACE",
							Value: "/workspace",
						},
						{
							Name:  "AGENT_ANVIL_MODE",
							Value: "record", // TODO: Make this configurable (record, replay, fork)
						},
						{
							Name:  "AGENT_ANVIL_REPLAY_FROM_STEP",
							Value: "0", // TODO: Set this value when in replay mode to specify which step to replay from
							// Value: "step-2", // Example value for replay mode
							// Leave empty or unset when not in replay mode
						},
						{
							Name:  "HTTP_PROXY",
							Value: "http://localhost:8080", // TODO: Replace with actual proxy URL if needed
						},
						{
							Name:  "HTTPS_PROXY",
							Value: "http://localhost:8080", // TODO: Replace with actual proxy URL if needed
						},
						// {
						// 	Name: "AGENT_ANVIL_API_KEY_FILE",
						// 	Value: "/etc/agent-anvil/secrets/anthropic-api-key", // TODO: Replace with actual file path
						// },
						// {
						// 	Name: "SSL_CERT_FILE",
						// 	Value: "/etc/agent-anvil/ca-cert.pem", // TODO: Replace with actual file path
						// },
					},
				},
				{
					Name:    "proxy",
					Image:   "busybox",                                                                  // TODO: Replace with the actual image needed for the proxy
					Command: []string{"/bin/sh", "-c"},                                                  // Placeholder command, replace with actual command for the proxy
					Args:    []string{"echo \"Pod running for AgentTask " + taskID + "\" && sleep 120"}, // Placeholder command, replace with actual command for the proxy
					VolumeMounts: []corev1.VolumeMount{
						{
							Name:      "task",
							MountPath: "/etc/agent-anvil/",
							ReadOnly:  true,
						},
						{
							Name:      "trace",
							MountPath: "/var/log/agent-anvil",
							ReadOnly:  false,
						},
					},
				},
			},
			Volumes: []corev1.Volume{
				{
					Name: "task",
					VolumeSource: corev1.VolumeSource{
						Projected: &corev1.ProjectedVolumeSource{
							Sources: []corev1.VolumeProjection{
								{
									ConfigMap: &corev1.ConfigMapProjection{
										LocalObjectReference: corev1.LocalObjectReference{
											Name: buildConfigMapName(agenttask),
										},
										Items: []corev1.KeyToPath{
											{
												Key:  "task.yaml",
												Path: "task.yaml",
											},
										},
									},
								},
								// {
								// 	ConfigMap: &corev1.ConfigMapProjection{
								// 		LocalObjectReference: corev1.LocalObjectReference{
								// 			Name: "proxy-config",
								// 		},
								// 	},
								// },
								// {
								// 	Secret: &corev1.SecretProjection{
								// 		LocalObjectReference: corev1.LocalObjectReference{
								// 			Name: "agent-anvil-api-key",
								// 		},
								// 	},
								// },
							},
						},
					},
				},
				{
					Name: "trace",
					VolumeSource: corev1.VolumeSource{
						EmptyDir: &corev1.EmptyDirVolumeSource{},
					},
				},
				{
					Name: "workspace",
					VolumeSource: corev1.VolumeSource{
						EmptyDir: &corev1.EmptyDirVolumeSource{},
					},
				},
			},

			RestartPolicy: corev1.RestartPolicyNever,
		},
	}

	return pod
}
