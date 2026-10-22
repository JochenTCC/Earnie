from ui.ehal_connection import render_ha_connection_form

# Stands in for the app shell: app.py shows queued flash notices before the page.
from ui.flash import render_flash_notices

render_flash_notices()

render_ha_connection_form(form_key="t_ha")
