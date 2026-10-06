# DECA · Grupo Peninsular

Aplicación web para emitir Documentos electrónicos de Control Administrativo (DeCA) para las sociedades del Grupo Peninsular.

Incluye selección de empresa emisora, numeración anual por sociedad, múltiples envíos, PDF nativo, QR con URL directa, histórico y versionado de modificaciones.

## Despliegue en Render

El repositorio incluye `render.yaml`. Build: `pip install -r requirements.txt`. Inicio: `gunicorn -w 1 -b 0.0.0.0:$PORT app:app`.

> El plan gratuito de Render usa almacenamiento local efímero. Para explotación real y conservación reglamentaria del histórico debe conectarse almacenamiento persistente antes de usarlo como archivo definitivo.
