{{- define "agent.labels" -}}
app.kubernetes.io/name: agent
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "agent.selectorLabels" -}}
app.kubernetes.io/name: agent
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
