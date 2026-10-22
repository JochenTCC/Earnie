from ui.pages import page_smarthome_backend

# Stands in for the app shell: app.py shows queued flash notices before the page.
from ui.flash import render_flash_notices

render_flash_notices()

page_smarthome_backend.render()
