# PRODUCT_DECISIONS.md — Studia

Registro de decisiones de producto. Formato: fecha · decisión · razón · estado.

## 2026-08-29 · El visor de PDF es una funcionalidad necesaria
- **Decisión:** M confirma que la app necesita un visor de PDF (ver el
  documento original, no solo el texto extraído). Queda como pendiente
  priorizado, no como idea opcional.
- **Bloqueo técnico:** hoy solo se almacena el texto extraído (`pdfs.text`);
  el binario del PDF se descarta tras la extracción. Un visor real requiere
  conservar el fichero original → decisión de almacenamiento pendiente.
- **Opciones de almacenamiento (decisión pendiente):**
  1. GridFS en Atlas: mínimo código nuevo, pero consume la cuota del M0
     (512 MB compartidos); inviable en free tier con volumen.
  2. Cloudflare R2 / S3 con URLs firmadas: R2 da 10 GB gratis sin coste de
     egreso. Más infra (credenciales, bucket, borrado en cascada), pero es la
     vía correcta para escalar. Recomendada.
  3. Previsualización de texto extraído (stopgap): coste cero, pero NO es un
     visor (sin maquetación/imágenes). Solo como paso previo opcional.
- **Implicaciones:** `DELETE /api/pdfs/{id}` deberá borrar también el fichero
  almacenado; guardar ficheros de usuario amplía la superficie de borrado/GDPR.
- **Estado:** PENDIENTE. Siguiente paso: decidir almacenamiento → implementar.
