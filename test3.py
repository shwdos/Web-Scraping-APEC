import pandas as pd
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
from bs4 import BeautifulSoup
import csv
import re

# Options pour le navigateur Firefox en mode headless
options = webdriver.FirefoxOptions()
options.headless = True

# Initialisation du navigateur Firefox
driver = webdriver.Firefox(options=options)
driver.set_page_load_timeout(100)

# URL de base pour la première page et les pages suivantes
base_url_first_page = "https://www.apec.fr/candidat/recherche-emploi.html/emploi?typesConvention=143684&typesConvention=143685&typesConvention=143686&typesConvention=143687&typesConvention=1437066"
base_url_next_pages = "https://www.apec.fr/candidat/recherche-emploi.html/emploi?page={page_number}&typesConvention=143684&typesConvention=143685&typesConvention=143686&typesConvention=143687&typesConvention=143706"

progress_file = 'scraping_progress_2024.json'

# Charger la progression sauvegardée
def load_progress():
    try:
        with open(progress_file, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return {'current_page': 1, 'data': []}

# Sauvegarder la progression
def save_progress(current_page, data):
    with open(progress_file, 'w') as file:
        json.dump({'current_page': current_page, 'data': data}, file)

# Fonction pour récupérer les liens vers chaque fiche de poste depuis une URL spécifique
def get_offer_links_from_url(url):
    driver.get(url)
    
    # Accepter automatiquement les cookies
    try:
        accept_cookies_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, 'onetrust-accept-btn-handler')))
        accept_cookies_button.click()
    except TimeoutException:
        pass
    
    offer_links = set()
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'div.container-result a[queryparamshandling="merge"]')))
        offer_elements = driver.find_elements(By.CSS_SELECTOR, 'div.container-result a[queryparamshandling="merge"]')
        
        for offer_element in offer_elements:
            try:
                offer_links.add(offer_element.get_attribute('href'))
            except StaleElementReferenceException:
                continue
    
    except TimeoutException:
        print(f"TimeoutException: Unable to fetch offer links from {url}")
    
    return offer_links

# Fonction pour récupérer les données détaillées de chaque offre
def process_offer_details(offer_link):
    try:
        driver.get(offer_link)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'ul.details-offer-list.mb-20')))
        soup = BeautifulSoup(driver.page_source, 'html.parser')

        job_data = {
            'company_name': '.',
            'nombre_postes': '.',  # Nouveau champ pour le nombre de postes
            'statut_CDD_CDI': '.',  # Nouveau champ pour le type de contrat
            'location': '.',
            'ville': '.',
            'departement': '.',
            'salary_raw': '.',
            'salary_average': None,
            'salary_minimum': None,
            'reference_apec': '.',
            'date_publication': '.',
            'mois_publication': None,
            'experience': '.',
            'experience_value': None,
            'travel_zone': '.',
            'langues': '.',
            'metier': '.',
            'secteur_activite': '.',
            'teletravail': '.',
            'description': '.'
        }

        details_list = soup.find('ul', class_='details-offer-list mb-20')
        if details_list:
            list_items = details_list.find_all('li')
            if len(list_items) >= 3:
                job_data['company_name'] = list_items[0].get_text(strip=True) or '.'
                
                # Extraction du nombre de postes et du type de contrat
                second_li_text = list_items[1].get_text(strip=True)
                job_data['nombre_postes'] = re.search(r'\d+', second_li_text).group() if re.search(r'\d+', second_li_text) else '.'
                job_data['statut_CDD_CDI'] = list_items[1].find_all('span')[0].get_text(strip=True) if list_items[1].find_all('span') else '.'

                job_data['location'] = list_items[2].get_text(strip=True) or '.'
                if re.search(r'.*- \d{2}$', job_data['location']):
                    job_data['ville'], job_data['departement'] = job_data['location'].split(' - ')
                    job_data['departement'] = int(job_data['departement'])

        salary_div = soup.find('div', class_='details-post')
        if salary_div:
            salary_header = salary_div.find('h4', string='Salaire')
            if salary_header:
                salary_value = salary_header.find_next_sibling('span').get_text(strip=True) or '.'
                job_data['salary_raw'] = salary_value

                if " - " in salary_value:
                    min_salary, max_salary = map(int, re.findall(r'\d+', salary_value))
                    job_data['salary_average'] = (min_salary + max_salary) / 2
                elif "A partir de" in salary_value:
                    min_salary = int(re.search(r'\d+', salary_value).group())
                    job_data['salary_minimum'] = min_salary
                elif "À négocier" in salary_value:
                    job_data['salary_raw'] = '.'
                elif " k€ brut annuel" in salary_value:
                    salaries = list(map(int, re.findall(r'\d+', salary_value)))
                    if len(salaries) == 1:
                        job_data['salary_minimum'] = salaries[0]
                    elif len(salaries) == 2:
                        job_data['salary_average'] = (salaries[0] + salaries[1]) / 2

        ref_offre_div = soup.find('div', class_='ref-offre')
        if ref_offre_div:
            job_data['reference_apec'] = re.search(r'Ref. Apec :\s*(\S+)', ref_offre_div.get_text(strip=True)).group(1)

        date_offre_div = soup.find('div', class_='date-offre mb-10')
        if date_offre_div:
            job_data['date_publication'] = re.search(r'Publiée le\s*(\d+/\d+/\d+)', date_offre_div.get_text(strip=True)).group(1)

        if job_data['date_publication'] != '.':
            job_data['mois_publication'] = int(job_data['date_publication'].split('/')[1])

        experience_tag = soup.find('h4', string='Expérience')
        if experience_tag:
            experience_text = experience_tag.find_next_sibling('span').get_text(strip=True) or '.'
            job_data['experience'] = experience_text
            match = re.search(r'\d+', experience_text)
            if match:
                job_data['experience_value'] = int(match.group())

        travel_zone_tag = soup.find('h4', string='Zone de déplacement')
        if travel_zone_tag:
            job_data['travel_zone'] = travel_zone_tag.find_next_sibling('span').get_text(strip=True) or '.'

        langues_section = soup.find('h5', string='Langues')
        if langues_section:
            langues_list = [f"{langue.get_text(strip=True)} ({niveau.find('h4').get_text(strip=True)})"
                            for langue, niveau in zip(langues_section.find_parent('div', class_='flex-collapse').find_all('div', class_='infos_skills'),
                                                     langues_section.find_parent('div', class_='flex-collapse').find_all('apec-competence-tooltip-niveau'))]
            job_data['langues'] = ', '.join(langues_list)

        metier_tag = soup.find('h4', string='Métier')
        if metier_tag:
            job_data['metier'] = metier_tag.find_next_sibling('span').get_text(strip=True) or '.'

        secteur_activite_tag = soup.find('h4', string='Secteur d’activité du poste')
        if secteur_activite_tag:
            job_data['secteur_activite'] = secteur_activite_tag.find_next_sibling('span').get_text(strip=True) or '.'

        teletravail_tag = soup.find('h4', string='Télétravail')
        if teletravail_tag:
            job_data['teletravail'] = teletravail_tag.find_next_sibling('span').get_text(strip=True) or '.'

        description_tag = soup.find('h4', string='Descriptif du poste')
        if description_tag:
            description_parts = [desc_part.get_text(strip=True) for desc_part in description_tag.find_parent().find_all('p')]
            job_data['description'] = ' '.join(description_parts) if description_parts else '.'

        return job_data
    
    except Exception as e:
        print(f"Erreur produite lors de la récupération des données de l'offre {offer_link}: {str(e)}")
        return None

# Fonction pour récupérer toutes les offres d'emploi
def scrape_job_offers(base_url_first_page, base_url_next_pages, max_pages=50):
    progress = load_progress()
    current_page = progress['current_page']
    all_job_data = progress['data']

    # Reprendre le scraping à partir de la page courante
    for page_number in range(current_page, max_pages + 1):
        url = base_url_next_pages.format(page_number=page_number)
        offer_links = get_offer_links_from_url(url)
        for offer_link in offer_links:
            job_data = process_offer_details(offer_link)
            if job_data:
                all_job_data.append(job_data)
        
        # Sauvegarder la progression après chaque page
        save_progress(page_number + 1, all_job_data)
    
    return all_job_data

# Appeler la fonction pour récupérer toutes les offres d'emploi
max_pages = 7751
all_job_data = scrape_job_offers(base_url_first_page, base_url_next_pages, max_pages)

# Sauvegarde des données dans un fichier CSV
def save_to_csv(job_data_list):
    csv_file = "offres_emploi_officielP.csv"
    fields = ['company_name', 'nombre_postes', 'statut_CDD_CDI', 'location', 'ville', 'departement', 'salary_raw', 'salary_average', 'salary_minimum', 'reference_apec', 'date_publication', 'mois_publication', 'experience', 'experience_value', 'travel_zone', 'langues', 'metier', 'secteur_activite', 'teletravail', 'description']
    with open(csv_file, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for data in job_data_list:
            writer.writerow(data)

# Enregistrement des données dans un fichier Excel
def save_to_excel(job_data_list):
    excel_file = "officiel_data_2024P.xlsx"
    df = pd.DataFrame(job_data_list)
    df.to_excel(excel_file, index=False)

# Appeler les fonctions pour sauvegarder les données
save_to_csv(all_job_data)
save_to_excel(all_job_data)

# Fermeture du navigateur
driver.quit()

print("Traitement terminé. Les données ont été sauvegardées dans offres_emploi_officielQ.csv et officiel_data_2024Q.xlsx.")
