package controller

import (
	"os"

	agenttasksv1 "github.com/amit397/agentanvil/api/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// agentImage is the Track-A SDK image. Override via AGENT_ANVIL_SDK_IMAGE for
// `kind load docker-image ...` flows during local development. The default tag
// is what `make sdk-build` produces.
func agentImage() string {
	if v := os.Getenv("AGENT_ANVIL_SDK_IMAGE"); v != "" {
		return v
	}
	return "agent-anvil-sdk:dev"
}

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
					Name:            "agent",
					Image:           agentImage(),
					ImagePullPolicy: corev1.PullIfNotPresent,
					// The SDK's entrypoint reads /etc/agent-anvil/task.yaml and writes
					// /var/log/agent-anvil/events.jsonl. No command/args override needed.
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
							Value: "record", // TODO: Make this configurable (record, replay, fork) — Phase 2A
						},
						{
							Name:  "AGENT_ANVIL_REPLAY_FROM_STEP",
							Value: "0",
						},
						{
							Name:  "AGENT_ANVIL_ECHO_EVENTS",
							Value: "1", // Mirror events to stdout so `kubectl logs` shows the trace until trace storage (Phase 2B) lands.
						},
						// HTTP_PROXY / HTTPS_PROXY are intentionally NOT set here yet.
						// The recording proxy sidecar lands in Phase 2A; until it exists,
						// pointing at the placeholder busybox sidecar would break egress
						// for any task that calls a real LLM. Tasks that need network must
						// run via the mock provider (provider: mock) for now.
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
					// Recording proxy is Phase 2A (Track A). For now this is a no-op
					// sidecar that waits for the agent to finish so the pod can transition
					// to Succeeded. When Phase 2A lands, replace image + command with the
					// real recording proxy from cmd/proxy.
					Name:    "proxy",
					Image:   "busybox",
					Command: []string{"/bin/sh", "-c"},
					Args:    []string{"echo \"proxy sidecar (Phase 2A stub) for " + taskID + "\" && sleep 30"},
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
