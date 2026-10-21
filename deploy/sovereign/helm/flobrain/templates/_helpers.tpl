{{- define "flobrain.labels" -}}
app.kubernetes.io/name: flobrain
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 }}
{{- end }}
{{/* Selector labels: kept to instance + component so upgrades from 0.1 keep the same (immutable) selectors. */}}
{{- define "flobrain.selector" -}}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}
{{- define "flobrain.image" -}}
{{ required "image.tag is required" .Values.image.tag | printf "%s:%s" .Values.image.repository }}
{{- end }}
{{- define "flobrain.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{ default .Release.Name .Values.serviceAccount.name }}
{{- else -}}
{{ default "default" .Values.serviceAccount.name }}
{{- end -}}
{{- end }}
{{- define "flobrain.env" -}}
envFrom:
  - configMapRef: { name: {{ .Release.Name }}-config }
  - secretRef: { name: {{ required "existingSecret is required (create it with kubectl; never put secrets in values)" .Values.existingSecret }} }
{{- end }}
{{/* Pod-level settings shared by every FloBrain pod (API image, Whisper, meeting bot). */}}
{{- define "flobrain.podSpec" -}}
serviceAccountName: {{ include "flobrain.serviceAccountName" . }}
automountServiceAccountToken: {{ .Values.serviceAccount.automountToken }}
securityContext: {{- toYaml .Values.podSecurityContext | nindent 2 }}
{{- with .Values.imagePullSecrets }}
imagePullSecrets: {{- toYaml . | nindent 2 }}
{{- end }}
{{- end }}
{{/* nodeSelector / tolerations / affinity for the API image pods. */}}
{{- define "flobrain.scheduling" -}}
{{- with .nodeSelector }}
nodeSelector: {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .tolerations }}
tolerations: {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .affinity }}
affinity: {{- toYaml . | nindent 2 }}
{{- end }}
{{- end }}
{{- define "flobrain.containerSecurity" -}}
securityContext: {{- toYaml .Values.containerSecurityContext | nindent 2 }}
{{- end }}
{{- define "flobrain.tmp" -}}
volumeMounts:
  - { name: tmp, mountPath: /tmp }
{{- end }}
{{- define "flobrain.configChecksum" -}}
checksum/config: {{ include (print .Template.BasePath "/configmap.yaml") . | sha256sum }}
{{- end }}
