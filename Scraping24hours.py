import sqlite3
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException
from bs4 import BeautifulSoup
import csv
import time
from concurrent.futures import ThreadPoolExecutor
import re
from datetime import datetime

# Options pour le navigateur Firefox en mode headless
options = webdriver.FirefoxOptions()
options.headless = True

# Initialisation du navigateur Firefox
driver = webdriver.Firefox(options=options)
driver.set_page_load_timeout(100)
driver.get('https://www.apec.fr/candidat/recherche-emploi.html/emploi?typesConvention=143684&typesConvention=143685&typesConvention=143686&typesConvention=143687&typesConvention=143706&anciennetePublication=101850')

# Accepter automatiquement les cookies si nécessaire
try:
    accept_cookies_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, 'onetrust-accept-btn-handler')))
    accept_cookies_button.click()
    print("Cookies acceptés.")
except TimeoutException:
    print("La bannière de consentement des cookies n'a pas été trouvée.")

# Connexion à la base de données SQLite
conn = sqlite3.connect('job_offers.db')
c = conn.cursor()

# Création de la table si elle n'existe pas déjà
c.execute('''CREATE TABLE IF NOT EXISTS job_offers
             (ref_apec TEXT PRIMARY KEY, url TEXT, company_name TEXT, statut_poste TEXT, location TEXT, ville TEXT, departement TEXT, salary_raw TEXT, salary_average TEXT, salary_minimum TEXT, date_publication TEXT, mois_publication TEXT, experience TEXT, experience_value TEXT, travel_zone TEXT, langues TEXT, metier TEXT, secteur_activite TEXT, teletravail TEXT, description TEXT)''')

# Fonction pour récupérer les liens vers chaque fiche de poste
def get_offer_links(driver):
    offer_links = set()
    page_count = 0

    while True:
        try:
            # Attendre que les éléments chargent
            WebDriverWait(driver, 10).until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'div.container-result a[queryparamshandling="merge"]')))
            
            # Récupérer les liens des offres sur la page actuelle
            offer_elements = driver.find_elements(By.CSS_SELECTOR, 'div.container-result a[queryparamshandling="merge"]')
            print("Nombre d'éléments trouvés sur la page actuelle :", len(offer_elements))
            
            for offer_element in offer_elements:
                try:
                    offer_link = offer_element.get_attribute('href')
                    offer_links.add(offer_link)
                except StaleElementReferenceException:
                    continue

            # Cliquer sur le bouton de la page suivante s'il existe
            try:
                next_page_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'li.page-item.next a.page-link')))
            
                # Faire défiler la page jusqu'au bouton pour le rendre cliquable
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center', inline: 'nearest'});", next_page_button)
                time.sleep(1)
                
                # Cliquer sur le bouton de la page suivante
                next_page_button.click()
                print("Cliquer sur le bouton de la page suivante")
                time.sleep(5)

                page_count += 1
                
            except TimeoutException:
                print("Le bouton de la page suivante n'a pas été trouvé.")
                break
            except NoSuchElementException:
                print("Pas de bouton de la page suivante trouvé, sortie de la boucle.")
                break
            except Exception as e:
                print(f"Erreur lors du clic sur le bouton de la page suivante : {str(e)}")

        except TimeoutException:
            print("Impossible de charger les éléments sur la page actuelle.")
            break
    
    return offer_links

# Fonction pour récupérer les données détaillées de chaque offre
def process_offer_details(offer_link):
    try:
        driver.get(offer_link)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, 'ul.details-offer-list.mb-20')))
        html_content = driver.page_source
        soup = BeautifulSoup(html_content, 'html.parser')

        # Récupération des données de chaque offre
        job_data = {
            'company_name': '.',
            'statut_poste': '.',
            'location': '.',
            'ville': '.',
            'departement': '.',
            'salary_raw': '.',
            'salary_average': '.',
            'salary_minimum': '.',
            'reference_apec': '.',
            'date_publication': '.',
            'mois_publication': '.',
            'experience': '.',
            'experience_value': '.',
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
                job_data['statut_poste'] = list_items[1].find('span').get_text(strip=True) if list_items[1].find('span') else '.'
                job_data['location'] = list_items[2].get_text(strip=True) or '.'
                if re.search(r'.*- \d{2}$', job_data['location']):
                    location_text = job_data['location']
                    job_data['ville'], job_data['departement'] = location_text.split(' - ')
                    job_data['departement'] = int(job_data['departement'])

        salary_div = soup.find('div', class_='details-post')
        if salary_div:
            salary_header = salary_div.find('h4', string='Salaire')
            if salary_header:
                salary_value = salary_header.find_next_sibling('span').get_text(strip=True) or '.'
                job_data['salary_raw'] = salary_value

                if " - " in salary_value:
                    salary_range = salary_value.split(' - ')
                    if len(salary_range) == 2:
                        try:
                            min_salary = re.sub(r'[^\d]', '', salary_range[0]).strip()
                            max_salary = re.sub(r'[^\d]', '', salary_range[1]).strip()
                            if min_salary and max_salary:
                                min_salary = int(min_salary)
                                max_salary = int(max_salary)
                                job_data['salary_average'] = (min_salary + max_salary) / 2
                        except ValueError:
                            print(f"Erreur de conversion pour la fourchette de salaire : {salary_range}")
                elif "A partir de" in salary_value:
                    try:
                        min_salary_match = re.search(r'\d+', salary_value)
                        if min_salary_match:
                            min_salary = min_salary_match.group(0)
                            if min_salary:
                                job_data['salary_minimum'] = int(min_salary)
                    except ValueError:
                        print(f"Erreur de conversion pour le salaire minimum : {salary_value}")
                elif "À négocier" in salary_value:
                    job_data['salary_raw'] = '.'
                elif " k€ brut annuel" in salary_value:
                    try:
                        salary_value = salary_value.replace(' k€ brut annuel', '')
                        salary_range = salary_value.split(' - ')
                        if len(salary_range) == 1:
                            job_data['salary_minimum'] = int(salary_range[0])
                        elif len(salary_range) == 2:
                            job_data['salary_average'] = (int(salary_range[0]) + int(salary_range[1])) / 2
                    except ValueError:
                        print(f"Erreur de conversion pour le format de salaire : {salary_value}")

                ref_offre_div = soup.find('div', class_='ref-offre')
        if ref_offre_div:
            ref_offre_text = ref_offre_div.get_text(strip=True)
            if 'Ref. Apec :' in ref_offre_text:
                job_data['reference_apec'] = ref_offre_text.split('Ref. Apec :')[1].strip().split(' ')[0] or '.'

        date_offre_div = soup.find('div', class_='date-offre mb-10')
        if date_offre_div:
            date_offre_text = date_offre_div.get_text(strip=True)
            if 'Publiée le' in date_offre_text:
                                job_data['date_publication'] = date_offre_text.split('Publiée le ')[1] or '.'

        if job_data['date_publication'] != '.':
            job_data['mois_publication'] = int(job_data['date_publication'].split('/')[1])

        experience_tag = soup.find('h4', string='Expérience')
        if experience_tag:
            experience_text = experience_tag.find_next_sibling('span').get_text(strip=True) or '.'
            job_data['experience'] = experience_text
            match = re.search(r'\d+', experience_text)
            if match:
                job_data['experience_value'] = int(match.group())
            else:
                job_data['experience_value'] = '.'

        travel_zone_tag = soup.find('h4', string='Zone de déplacement')
        if travel_zone_tag:
            job_data['travel_zone'] = travel_zone_tag.find_next_sibling('span').get_text(strip=True) or '.'

        statut_tag = soup.find('h4', string='Statut du poste')
        if statut_tag:
            statut_text = statut_tag.find_next_sibling('span').get_text(strip=True) or '.'
            job_data['statut_poste'] = statut_text

        langues_section = soup.find('h5', string='Langues')
        if langues_section:
            parent_div = langues_section.find_parent('div', class_='flex-collapse')
            if parent_div:
                langues_structure = parent_div.find_all('div', class_='added-skills-language')
                langues_list = []
                for structure in langues_structure:
                    langues_elements = structure.find_all('div', class_='infos_skills')
                    for element in langues_elements:
                        langue = element.find('p').get_text(strip=True) or '.'
                        niveau_tag = element.find_next_sibling('apec-competence-tooltip-niveau')
                        if niveau_tag:
                            niveau = niveau_tag.find('h4').get_text(strip=True) or '.'
                            langues_list.append(f"{langue} ({niveau})")
                if langues_list:
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
        else:
            job_data['teletravail'] = '.'

        description_tag = soup.find('h4', string='Descriptif du poste')
        if description_tag:
            next_element = description_tag.find_next_sibling()
            description_parts = []
            while next_element and next_element.name != 'h4' and next_element.get_text(strip=True) != 'Profil recherché':
                description_parts.append(next_element.get_text(strip=True) or '.')
                next_element = next_element.find_next_sibling()
            job_data['description'] = ' '.join(description_parts)

        return job_data

    except Exception as e:
        print(f"Une erreur s'est produite lors de la récupération des données de l'offre {offer_link}: {str(e)}")
        return None

# Fonction pour récupérer les données en parallèle
def scrape_offers_parallel(offer_links):
    job_data_list = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(process_offer_details, offer_links)
        for job_data in results:
            if job_data:
                job_data_list.append(job_data)
    return job_data_list

# Récupérer les liens vers les offres
offer_links = get_offer_links(driver)

# Scraping en parallèle des offres
job_data_list = scrape_offers_parallel(offer_links)

# Sauvegarde des données dans un fichier CSV
def save_to_csv(job_data_list):
    csv_file = f"offres_emploi_{datetime.now().strftime('%Y%m%d')}.csv"
    fields = ['company_name', 'statut_poste', 'location', 'ville', 'departement', 'salary_raw', 'salary_average', 'salary_minimum', 'reference_apec', 'date_publication', 'mois_publication', 'experience', 'experience_value', 'travel_zone', 'langues', 'metier', 'secteur_activite', 'teletravail', 'description']
    with open(csv_file, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for data in job_data_list:
            writer.writerow(data)

# Enregistrement des données dans un fichier Excel
def save_to_excel(job_data_list):
    excel_file = f"offres_emploi_{datetime.now().strftime('%Y%m%d')}.xlsx"
    df = pd.DataFrame(job_data_list)
    df.to_excel(excel_file, index=False)

# Insertion des données dans la base de données
def save_to_db(job_data_list):
    with sqlite3.connect('job_offers.db') as conn:
        c = conn.cursor()
        for data in job_data_list:
            try:
                c.execute('''INSERT OR IGNORE INTO job_offers (ref_apec, url, company_name, statut_poste, location, ville, departement, salary_raw, salary_average, salary_minimum, date_publication, mois_publication, experience, experience_value, travel_zone, langues, metier, secteur_activite, teletravail, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                (data['reference_apec'], data.get('url', '.'), data['company_name'], data['statut_poste'], data['location'], data['ville'], data['departement'], data['salary_raw'], data['salary_average'], data['salary_minimum'], data['date_publication'], data['mois_publication'], data['experience'], data['experience_value'], data['travel_zone'], data['langues'], data['metier'], data['secteur_activite'], data['teletravail'], data['description']))
                conn.commit()
            except Exception as e:
                print(f"Erreur lors de l'insertion des données dans la base de données : {str(e)}")

# Appeler les fonctions pour sauvegarder les données
save_to_csv(job_data_list)
save_to_excel(job_data_list)
save_to_db(job_data_list)

# Fermeture du navigateur
driver.quit()

print(f"Les données des offres ont été enregistrées dans les fichiers CSV, Excel et la base de données.")

               
