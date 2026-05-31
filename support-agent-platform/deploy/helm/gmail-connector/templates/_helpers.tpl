{{- define "gmailconnector.labels" -}}
app.kubernetes.io/name: gmail-connector
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "gmailconnector.selectorLabels" -}}
app.kubernetes.io/name: gmail-connector
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
