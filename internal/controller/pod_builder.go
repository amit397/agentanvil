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

	pod := &corev1.Pod{
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
					Name:    "agent",
					Image:   "nginx",
					Command: []string{"/bin/sh", "-c"},                                                 // Placeholder command, replace with actual command for the task
					Args:    []string{"echo \"Pod running for AgentTask " + taskID + "\" && sleep 60"}, // Placeholder command, replace with actual command for the task
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
				},
				{
					Name:    "proxy",
					Image:   "busybox",                                                                   // TODO: Replace with the actual image needed for the proxy
					Command: []string{"/bin/sh", "-c"},                                                   // Placeholder command, replace with actual command for the proxy
					Args:    []string{"echo \"Proxy running for AgentTask " + taskID + "\" && sleep 60"}, // Placeholder command, replace with actual command for the proxy
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
											Name: agenttask.Name + "-config",
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
