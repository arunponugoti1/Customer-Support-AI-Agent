{{- define "approval.labels" -}}
app.kubernetes.io/name: approval
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "approval.selectorLabels" -}}
app.kubernetes.io/name: approval
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
