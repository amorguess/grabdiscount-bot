from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import os
import shutil

SELENIUM_PROFILE_DIR = os.path.abspath("chrome_selenium_profile")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

options = Options()
options.add_argument(f"user-data-dir={SELENIUM_PROFILE_DIR}")
options.add_experimental_option("detach", True)

# Facultatif : pour ne pas que la fenêtre s'affiche en plein écran ou ailleurs
# options.add_argument("--start-maximized")
# options.add_argument("--window-position=100,100")



# Nettoyage du cache Chrome
cache_path = os.path.join(BASE_DIR, "browser_data", "Default", "Cache")
if os.path.exists(cache_path):
    shutil.rmtree(cache_path)

driver = webdriver.Chrome(options=options)

# Tu peux ouvrir n'importe quelle URL si tu veux :
driver.get("https://www.icloud.com/mail/")

# Le navigateur reste ouvert grâce à `detach=True`
