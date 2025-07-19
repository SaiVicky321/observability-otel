{{- define "otel-collector.fullname" -}}
{{- printf "%s-%s" .Release.Name "otel-collector" | trunc 63 | trimSuffix "-" -}}
{{- end }}
