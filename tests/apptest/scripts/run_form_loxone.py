from ui.setup_dotenv import render_loxone_credentials_form

# Stands in for the app shell: app.py shows queued flash notices before the page.
from ui.flash import render_flash_notices

render_flash_notices()

render_loxone_credentials_form(form_key="t_loxone")
