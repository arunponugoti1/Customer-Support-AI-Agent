{{- define "llmproxy.labels" -}}
app.kubernetes.io/name: llm-proxy
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "llmproxy.selectorLabels" -}}
app.kubernetes.io/name: llm-proxy
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
