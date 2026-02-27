# 모든 미국 주(50개+DC) 추가 및 각 주별 주요 도시 업데이트
# 누락된 주: AL, AK, AR, DE, ID, IA, LA, ME, MS, MT, NH, NM, ND, PA, RI, SC, SD, VT, VA, WV, WI, WY, DC

from django.db import migrations

# (region_code, state_code, state_name, slug, city_name, order)
# WEST: AK, AZ, CA, CO, HI, ID, MT, NV, NM, OR, UT, WA, WY
# CENTRAL: IA, IL, IN, KS, MI, MN, MO, ND, NE, OH, OK, SD, TX, WI
# EAST: AL, AR, CT, DE, FL, GA, KY, LA, MA, MD, ME, MS, NC, NH, NJ, NY, PA, RI, SC, TN, VA, VT, WV, DC
MISSING_STATES_CITIES = [
    # === WEST - 누락된 주 ===
    # AK - Alaska
    ('WEST', 'AK', 'Alaska', 'ak-anchorage', 'Anchorage', 1),
    ('WEST', 'AK', 'Alaska', 'ak-fairbanks', 'Fairbanks', 2),
    ('WEST', 'AK', 'Alaska', 'ak-juneau', 'Juneau', 3),
    ('WEST', 'AK', 'Alaska', 'ak-sitka', 'Sitka', 4),
    ('WEST', 'AK', 'Alaska', 'ak-ketchikan', 'Ketchikan', 5),
    # ID - Idaho
    ('WEST', 'ID', 'Idaho', 'id-boise', 'Boise', 1),
    ('WEST', 'ID', 'Idaho', 'id-meridian', 'Meridian', 2),
    ('WEST', 'ID', 'Idaho', 'id-nampa', 'Nampa', 3),
    ('WEST', 'ID', 'Idaho', 'id-idaho-falls', 'Idaho Falls', 4),
    ('WEST', 'ID', 'Idaho', 'id-pocatello', 'Pocatello', 5),
    ('WEST', 'ID', 'Idaho', 'id-caldwell', 'Caldwell', 6),
    ('WEST', 'ID', 'Idaho', 'id-coeur-dalene', "Coeur d'Alene", 7),
    ('WEST', 'ID', 'Idaho', 'id-twin-falls', 'Twin Falls', 8),
    # MT - Montana
    ('WEST', 'MT', 'Montana', 'mt-billings', 'Billings', 1),
    ('WEST', 'MT', 'Montana', 'mt-missoula', 'Missoula', 2),
    ('WEST', 'MT', 'Montana', 'mt-great-falls', 'Great Falls', 3),
    ('WEST', 'MT', 'Montana', 'mt-bozeman', 'Bozeman', 4),
    ('WEST', 'MT', 'Montana', 'mt-helena', 'Helena', 5),
    ('WEST', 'MT', 'Montana', 'mt-kalispell', 'Kalispell', 6),
    # NM - New Mexico
    ('WEST', 'NM', 'New Mexico', 'nm-albuquerque', 'Albuquerque', 1),
    ('WEST', 'NM', 'New Mexico', 'nm-las-cruces', 'Las Cruces', 2),
    ('WEST', 'NM', 'New Mexico', 'nm-santa-fe', 'Santa Fe', 3),
    ('WEST', 'NM', 'New Mexico', 'nm-roswell', 'Roswell', 4),
    ('WEST', 'NM', 'New Mexico', 'nm-farmington', 'Farmington', 5),
    ('WEST', 'NM', 'New Mexico', 'nm-clovis', 'Clovis', 6),
    ('WEST', 'NM', 'New Mexico', 'nm-rio-rancho', 'Rio Rancho', 7),
    # WY - Wyoming
    ('WEST', 'WY', 'Wyoming', 'wy-cheyenne', 'Cheyenne', 1),
    ('WEST', 'WY', 'Wyoming', 'wy-casper', 'Casper', 2),
    ('WEST', 'WY', 'Wyoming', 'wy-laramie', 'Laramie', 3),
    ('WEST', 'WY', 'Wyoming', 'wy-gillette', 'Gillette', 4),
    ('WEST', 'WY', 'Wyoming', 'wy-rock-springs', 'Rock Springs', 5),
    # === CENTRAL - 누락된 주 ===
    # IA - Iowa
    ('CENTRAL', 'IA', 'Iowa', 'ia-des-moines', 'Des Moines', 1),
    ('CENTRAL', 'IA', 'Iowa', 'ia-cedar-rapids', 'Cedar Rapids', 2),
    ('CENTRAL', 'IA', 'Iowa', 'ia-davenport', 'Davenport', 3),
    ('CENTRAL', 'IA', 'Iowa', 'ia-sioux-city', 'Sioux City', 4),
    ('CENTRAL', 'IA', 'Iowa', 'ia-iowa-city', 'Iowa City', 5),
    ('CENTRAL', 'IA', 'Iowa', 'ia-waterloo', 'Waterloo', 6),
    ('CENTRAL', 'IA', 'Iowa', 'ia-ames', 'Ames', 7),
    ('CENTRAL', 'IA', 'Iowa', 'ia-west-des-moines', 'West Des Moines', 8),
    # ND - North Dakota
    ('CENTRAL', 'ND', 'North Dakota', 'nd-fargo', 'Fargo', 1),
    ('CENTRAL', 'ND', 'North Dakota', 'nd-bismarck', 'Bismarck', 2),
    ('CENTRAL', 'ND', 'North Dakota', 'nd-grand-forks', 'Grand Forks', 3),
    ('CENTRAL', 'ND', 'North Dakota', 'nd-minot', 'Minot', 4),
    ('CENTRAL', 'ND', 'North Dakota', 'nd-west-fargo', 'West Fargo', 5),
    # SD - South Dakota
    ('CENTRAL', 'SD', 'South Dakota', 'sd-sioux-falls', 'Sioux Falls', 1),
    ('CENTRAL', 'SD', 'South Dakota', 'sd-rapid-city', 'Rapid City', 2),
    ('CENTRAL', 'SD', 'South Dakota', 'sd-aberdeen', 'Aberdeen', 3),
    ('CENTRAL', 'SD', 'South Dakota', 'sd-brookings', 'Brookings', 4),
    ('CENTRAL', 'SD', 'South Dakota', 'sd-watertown', 'Watertown', 5),
    # WI - Wisconsin
    ('CENTRAL', 'WI', 'Wisconsin', 'wi-milwaukee', 'Milwaukee', 1),
    ('CENTRAL', 'WI', 'Wisconsin', 'wi-madison', 'Madison', 2),
    ('CENTRAL', 'WI', 'Wisconsin', 'wi-green-bay', 'Green Bay', 3),
    ('CENTRAL', 'WI', 'Wisconsin', 'wi-kenosha', 'Kenosha', 4),
    ('CENTRAL', 'WI', 'Wisconsin', 'wi-racine', 'Racine', 5),
    ('CENTRAL', 'WI', 'Wisconsin', 'wi-appleton', 'Appleton', 6),
    ('CENTRAL', 'WI', 'Wisconsin', 'wi-waukesha', 'Waukesha', 7),
    ('CENTRAL', 'WI', 'Wisconsin', 'wi-oshkosh', 'Oshkosh', 8),
    ('CENTRAL', 'WI', 'Wisconsin', 'wi-eau-claire', 'Eau Claire', 9),
    ('CENTRAL', 'WI', 'Wisconsin', 'wi-janesville', 'Janesville', 10),
    # === EAST - 누락된 주 ===
    # AL - Alabama
    ('EAST', 'AL', 'Alabama', 'al-birmingham', 'Birmingham', 1),
    ('EAST', 'AL', 'Alabama', 'al-montgomery', 'Montgomery', 2),
    ('EAST', 'AL', 'Alabama', 'al-huntsville', 'Huntsville', 3),
    ('EAST', 'AL', 'Alabama', 'al-mobile', 'Mobile', 4),
    ('EAST', 'AL', 'Alabama', 'al-tuscaloosa', 'Tuscaloosa', 5),
    ('EAST', 'AL', 'Alabama', 'al-hoover', 'Hoover', 6),
    ('EAST', 'AL', 'Alabama', 'al-dothan', 'Dothan', 7),
    ('EAST', 'AL', 'Alabama', 'al-auburn', 'Auburn', 8),
    ('EAST', 'AL', 'Alabama', 'al-decatur', 'Decatur', 9),
    # AR - Arkansas
    ('EAST', 'AR', 'Arkansas', 'ar-little-rock', 'Little Rock', 1),
    ('EAST', 'AR', 'Arkansas', 'ar-fort-smith', 'Fort Smith', 2),
    ('EAST', 'AR', 'Arkansas', 'ar-fayetteville', 'Fayetteville', 3),
    ('EAST', 'AR', 'Arkansas', 'ar-springdale', 'Springdale', 4),
    ('EAST', 'AR', 'Arkansas', 'ar-jonesboro', 'Jonesboro', 5),
    ('EAST', 'AR', 'Arkansas', 'ar-rogers', 'Rogers', 6),
    ('EAST', 'AR', 'Arkansas', 'ar-conway', 'Conway', 7),
    # DE - Delaware
    ('EAST', 'DE', 'Delaware', 'de-wilmington', 'Wilmington', 1),
    ('EAST', 'DE', 'Delaware', 'de-dover', 'Dover', 2),
    ('EAST', 'DE', 'Delaware', 'de-newark', 'Newark', 3),
    ('EAST', 'DE', 'Delaware', 'de-middletown', 'Middletown', 4),
    ('EAST', 'DE', 'Delaware', 'de-smyrna', 'Smyrna', 5),
    # LA - Louisiana
    ('EAST', 'LA', 'Louisiana', 'la-new-orleans', 'New Orleans', 1),
    ('EAST', 'LA', 'Louisiana', 'la-baton-rouge', 'Baton Rouge', 2),
    ('EAST', 'LA', 'Louisiana', 'la-shreveport', 'Shreveport', 3),
    ('EAST', 'LA', 'Louisiana', 'la-metairie', 'Metairie', 4),
    ('EAST', 'LA', 'Louisiana', 'la-lafayette', 'Lafayette', 5),
    ('EAST', 'LA', 'Louisiana', 'la-lake-charles', 'Lake Charles', 6),
    ('EAST', 'LA', 'Louisiana', 'la-kenner', 'Kenner', 7),
    ('EAST', 'LA', 'Louisiana', 'la-bossier-city', 'Bossier City', 8),
    # ME - Maine
    ('EAST', 'ME', 'Maine', 'me-portland', 'Portland', 1),
    ('EAST', 'ME', 'Maine', 'me-lewiston', 'Lewiston', 2),
    ('EAST', 'ME', 'Maine', 'me-bangor', 'Bangor', 3),
    ('EAST', 'ME', 'Maine', 'me-south-portland', 'South Portland', 4),
    ('EAST', 'ME', 'Maine', 'me-auburn', 'Auburn', 5),
    ('EAST', 'ME', 'Maine', 'me-biddeford', 'Biddeford', 6),
    ('EAST', 'ME', 'Maine', 'me-sanford', 'Sanford', 7),
    # MS - Mississippi
    ('EAST', 'MS', 'Mississippi', 'ms-jackson', 'Jackson', 1),
    ('EAST', 'MS', 'Mississippi', 'ms-gulfport', 'Gulfport', 2),
    ('EAST', 'MS', 'Mississippi', 'ms-hattiesburg', 'Hattiesburg', 3),
    ('EAST', 'MS', 'Mississippi', 'ms-southaven', 'Southaven', 4),
    ('EAST', 'MS', 'Mississippi', 'ms-biloxi', 'Biloxi', 5),
    ('EAST', 'MS', 'Mississippi', 'ms-meridian', 'Meridian', 6),
    ('EAST', 'MS', 'Mississippi', 'ms-tupelo', 'Tupelo', 7),
    ('EAST', 'MS', 'Mississippi', 'ms-olive-branch', 'Olive Branch', 8),
    # NH - New Hampshire
    ('EAST', 'NH', 'New Hampshire', 'nh-manchester', 'Manchester', 1),
    ('EAST', 'NH', 'New Hampshire', 'nh-nashua', 'Nashua', 2),
    ('EAST', 'NH', 'New Hampshire', 'nh-concord', 'Concord', 3),
    ('EAST', 'NH', 'New Hampshire', 'nh-derry', 'Derry', 4),
    ('EAST', 'NH', 'New Hampshire', 'nh-dover', 'Dover', 5),
    ('EAST', 'NH', 'New Hampshire', 'nh-rochester', 'Rochester', 6),
    ('EAST', 'NH', 'New Hampshire', 'nh-salem', 'Salem', 7),
    # PA - Pennsylvania
    ('EAST', 'PA', 'Pennsylvania', 'pa-philadelphia', 'Philadelphia', 1),
    ('EAST', 'PA', 'Pennsylvania', 'pa-pittsburgh', 'Pittsburgh', 2),
    ('EAST', 'PA', 'Pennsylvania', 'pa-allentown', 'Allentown', 3),
    ('EAST', 'PA', 'Pennsylvania', 'pa-reading', 'Reading', 4),
    ('EAST', 'PA', 'Pennsylvania', 'pa-scranton', 'Scranton', 5),
    ('EAST', 'PA', 'Pennsylvania', 'pa-bethlehem', 'Bethlehem', 6),
    ('EAST', 'PA', 'Pennsylvania', 'pa-lancaster', 'Lancaster', 7),
    ('EAST', 'PA', 'Pennsylvania', 'pa-harrisburg', 'Harrisburg', 8),
    ('EAST', 'PA', 'Pennsylvania', 'pa-altoona', 'Altoona', 9),
    ('EAST', 'PA', 'Pennsylvania', 'pa-york', 'York', 10),
    ('EAST', 'PA', 'Pennsylvania', 'pa-state-college', 'State College', 11),
    ('EAST', 'PA', 'Pennsylvania', 'pa-wilkes-barre', 'Wilkes-Barre', 12),
    # RI - Rhode Island
    ('EAST', 'RI', 'Rhode Island', 'ri-providence', 'Providence', 1),
    ('EAST', 'RI', 'Rhode Island', 'ri-warwick', 'Warwick', 2),
    ('EAST', 'RI', 'Rhode Island', 'ri-cranston', 'Cranston', 3),
    ('EAST', 'RI', 'Rhode Island', 'ri-pawtucket', 'Pawtucket', 4),
    ('EAST', 'RI', 'Rhode Island', 'ri-east-providence', 'East Providence', 5),
    ('EAST', 'RI', 'Rhode Island', 'ri-woonsocket', 'Woonsocket', 6),
    # SC - South Carolina
    ('EAST', 'SC', 'South Carolina', 'sc-columbia', 'Columbia', 1),
    ('EAST', 'SC', 'South Carolina', 'sc-charleston', 'Charleston', 2),
    ('EAST', 'SC', 'South Carolina', 'sc-north-charleston', 'North Charleston', 3),
    ('EAST', 'SC', 'South Carolina', 'sc-greenville', 'Greenville', 4),
    ('EAST', 'SC', 'South Carolina', 'sc-rock-hill', 'Rock Hill', 5),
    ('EAST', 'SC', 'South Carolina', 'sc-mount-pleasant', 'Mount Pleasant', 6),
    ('EAST', 'SC', 'South Carolina', 'sc-sumter', 'Sumter', 7),
    ('EAST', 'SC', 'South Carolina', 'sc-goose-creek', 'Goose Creek', 8),
    ('EAST', 'SC', 'South Carolina', 'sc-hilton-head', 'Hilton Head Island', 9),
    ('EAST', 'SC', 'South Carolina', 'sc-florence', 'Florence', 10),
    # VT - Vermont
    ('EAST', 'VT', 'Vermont', 'vt-burlington', 'Burlington', 1),
    ('EAST', 'VT', 'Vermont', 'vt-south-burlington', 'South Burlington', 2),
    ('EAST', 'VT', 'Vermont', 'vt-rutland', 'Rutland', 3),
    ('EAST', 'VT', 'Vermont', 'vt-montpelier', 'Montpelier', 4),
    ('EAST', 'VT', 'Vermont', 'vt-barre', 'Barre', 5),
    # VA - Virginia
    ('EAST', 'VA', 'Virginia', 'va-virginia-beach', 'Virginia Beach', 1),
    ('EAST', 'VA', 'Virginia', 'va-norfolk', 'Norfolk', 2),
    ('EAST', 'VA', 'Virginia', 'va-chesapeake', 'Chesapeake', 3),
    ('EAST', 'VA', 'Virginia', 'va-richmond', 'Richmond', 4),
    ('EAST', 'VA', 'Virginia', 'va-arlington', 'Arlington', 5),
    ('EAST', 'VA', 'Virginia', 'va-newport-news', 'Newport News', 6),
    ('EAST', 'VA', 'Virginia', 'va-alexandria', 'Alexandria', 7),
    ('EAST', 'VA', 'Virginia', 'va-hampton', 'Hampton', 8),
    ('EAST', 'VA', 'Virginia', 'va-roanoke', 'Roanoke', 9),
    ('EAST', 'VA', 'Virginia', 'va-portsmouth', 'Portsmouth', 10),
    ('EAST', 'VA', 'Virginia', 'va-suffolk', 'Suffolk', 11),
    ('EAST', 'VA', 'Virginia', 'va-lynchburg', 'Lynchburg', 12),
    # WV - West Virginia
    ('EAST', 'WV', 'West Virginia', 'wv-charleston', 'Charleston', 1),
    ('EAST', 'WV', 'West Virginia', 'wv-huntington', 'Huntington', 2),
    ('EAST', 'WV', 'West Virginia', 'wv-morgantown', 'Morgantown', 3),
    ('EAST', 'WV', 'West Virginia', 'wv-parkersburg', 'Parkersburg', 4),
    ('EAST', 'WV', 'West Virginia', 'wv-wheeling', 'Wheeling', 5),
    ('EAST', 'WV', 'West Virginia', 'wv-weirton', 'Weirton', 6),
    # DC - District of Columbia
    ('EAST', 'DC', 'District of Columbia', 'dc-washington', 'Washington', 1),
]


def add_states_and_cities(apps, schema_editor):
    Region = apps.get_model('community', 'Region')
    Area = apps.get_model('community', 'Area')
    region_map = {r.code: r for r in Region.objects.all()}
    rows = MISSING_STATES_CITIES
    for reg_code, state_code, state_name, slug, city_name, order in rows:
        region = region_map.get(reg_code)
        if not region:
            continue
        Area.objects.get_or_create(
            slug=slug,
            defaults={
                'region': region,
                'state_code': state_code,
                'state_name': state_name,
                'city_name': city_name,
                'order': order,
            },
        )
    # 기존 Area의 state_name이 비어있으면 업데이트 (도시별 state_name 보강)
    state_names = {
        'AZ': 'Arizona', 'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut',
        'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii', 'IL': 'Illinois', 'IN': 'Indiana',
        'KS': 'Kansas', 'KY': 'Kentucky', 'MA': 'Massachusetts', 'MD': 'Maryland',
        'MI': 'Michigan', 'MN': 'Minnesota', 'MO': 'Missouri', 'NC': 'North Carolina',
        'NE': 'Nebraska', 'NJ': 'New Jersey', 'NV': 'Nevada', 'NY': 'New York',
        'OH': 'Ohio', 'OK': 'Oklahoma', 'OR': 'Oregon', 'TN': 'Tennessee',
        'TX': 'Texas', 'UT': 'Utah', 'WA': 'Washington',
    }
    for area in Area.objects.filter(state_name=''):
        area.state_name = state_names.get(area.state_code, area.state_code)
        area.save(update_fields=['state_name'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('community', '0004_add_all_state_cities')]
    operations = [migrations.RunPython(add_states_and_cities, noop)]
