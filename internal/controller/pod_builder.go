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
					Name:    "agent-task-container",
					Image:   "busybox",                                                                 // TODO: Replace with the actual image needed for the task
					Command: []string{"/bin/sh", "-c"},                                                 // Placeholder command, replace with actual command for the task
					Args:    []string{"echo \"Pod running for AgentTask " + taskID + "\" && sleep 30"}, // Placeholder command, replace with actual command for the task
				},
			},
			RestartPolicy: corev1.RestartPolicyNever,
		},
	}

	return pod
}
