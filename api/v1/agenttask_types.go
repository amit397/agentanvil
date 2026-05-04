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

package v1

import (
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// EDIT THIS FILE!  THIS IS SCAFFOLDING FOR YOU TO OWN!
// NOTE: json tags are required.  Any new fields you add must have json tags for the fields to be serialized.

// AgentTaskSpec defines the desired state of AgentTask
type AgentTaskSpec struct {
	// Required: What the agent should do
	Prompt       string `json:"prompt"`
	SystemPrompt string `json:"systemPrompt"`

	// Required: Model configuration for the agent
	Model *ModelSpec `json:"model"`
	Tools []ToolSpec `json:"tools"`

	// Optional: Workspace configuration for the agent
	Workspace *WorkspaceSpec `json:"workspace,omitempty"`

	// Optional: Limitations and policies for the agent task
	TimeoutSeconds   *int64                `json:"timeoutSeconds,omitempty"`
	MaxSteps         *int64                `json:"maxSteps,omitempty"`
	Resources        *ResourceSpec         `json:"resources,omitempty"`
	CheckpointPolicy *CheckpointPolicySpec `json:"checkpointPolicy,omitempty"`

	// Optional: Replay configuration for resuming from a previous checkpoint
	Replay *ReplaySpec `json:"replay,omitempty"`
}

// AgentTaskStatus defines the observed state of AgentTask.
type AgentTaskStatus struct {
	Phase       PhaseType          `json:"phase,omitempty"`
	CurrentStep int64              `json:"currentStep,omitempty"`
	StartedAt   *metav1.Time       `json:"startedAt,omitempty"`
	FinishedAt  *metav1.Time       `json:"finishedAt,omitempty"`
	TraceURL    string             `json:"traceURL"`
	PodName     string             `json:"podName"`
	Reason      string             `json:"reason,omitempty"`
	Conditions  []metav1.Condition `json:"conditions,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status

// AgentTask is the Schema for the agenttasks API
type AgentTask struct {
	metav1.TypeMeta `json:",inline"`

	// metadata is a standard object metadata
	// +optional
	metav1.ObjectMeta `json:"metadata,omitzero"`

	// spec defines the desired state of AgentTask
	// +required
	Spec AgentTaskSpec `json:"spec"`

	// status defines the observed state of AgentTask
	// +optional
	Status AgentTaskStatus `json:"status,omitzero"`
}

// +kubebuilder:object:root=true

// AgentTaskList contains a list of AgentTask
type AgentTaskList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitzero"`
	Items           []AgentTask `json:"items"`
}

// Helper structs and types for AgentTaskSpec
type APIKeySecretRef struct {
	Name string `json:"name,omitempty"`
	Key  string `json:"key,omitempty"`
}

type ModelSpec struct {
	Provider        string           `json:"provider,omitempty"`
	Name            string           `json:"name,omitempty"`
	APIKeySecretRef *APIKeySecretRef `json:"apiKeySecretRef,omitempty"`
	Params          map[string]any   `json:"params,omitempty"`
}

type ToolSpec struct {
	Name           string `json:"name,omitempty"`
	TimeoutSeconds *int64 `json:"timeoutSeconds"`
}

type WorkspaceSpec struct {
	BaseImage   string   `json:"baseImage,omitempty"`
	InitCommand []string `json:"initCommand,omitempty"`
}

type ResourceSpec struct {
	CPU              resource.Quantity `json:"cpu,omitempty"`
	Memory           resource.Quantity `json:"memory,omitempty"`
	EphemeralStorage resource.Quantity `json:"ephemeralStorage,omitempty"`
}

type CheckpointMode string

const (
	Manual    CheckpointMode = "Manual"
	EveryStep CheckpointMode = "EveryStep"
	Interval  CheckpointMode = "Interval"
)

type CheckpointPolicySpec struct {
	Mode            CheckpointMode `json:"mode"`
	IntervalSeconds *int64         `json:"intervalSeconds"`
}

type ReplaySpec struct {
	CheckpointID string `json:"checkpointId,omitempty"`
	FromStep     int64  `json:"fromStep,omitempty"`
}

// Helper types for AgentTaskStatus
type PhaseType string

const (
	Pending       PhaseType = "Pending"
	Provisioning  PhaseType = "Provisioning"
	Running       PhaseType = "Running"
	Checkpointing PhaseType = "Checkpointing"
	Completed     PhaseType = "Completed"
	Failed        PhaseType = "Failed"
	Evicted       PhaseType = "Evicted"
)

func init() {
	SchemeBuilder.Register(&AgentTask{}, &AgentTaskList{})
}
