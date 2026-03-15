# 각 주(State)별 주요 도시 추가 - 커버 도시 선택용

from django.db import migrations


# (region_code, state_code, state_name, slug, city_name, order)
# 기존: charlotte, raleigh 이미 있음. 나머지 추가
EXTRA_CITIES = [
    # NC - North Carolina (EAST)
    ('EAST', 'NC', 'North Carolina', 'nc-greensboro', 'Greensboro', 13),
    ('EAST', 'NC', 'North Carolina', 'nc-durham', 'Durham', 14),
    ('EAST', 'NC', 'North Carolina', 'nc-winston-salem', 'Winston-Salem', 15),
    ('EAST', 'NC', 'North Carolina', 'nc-fayetteville', 'Fayetteville', 16),
    ('EAST', 'NC', 'North Carolina', 'nc-cary', 'Cary', 17),
    ('EAST', 'NC', 'North Carolina', 'nc-wilmington', 'Wilmington', 18),
    ('EAST', 'NC', 'North Carolina', 'nc-high-point', 'High Point', 19),
    ('EAST', 'NC', 'North Carolina', 'nc-concord', 'Concord', 20),
    ('EAST', 'NC', 'North Carolina', 'nc-asheville', 'Asheville', 21),
    ('EAST', 'NC', 'North Carolina', 'nc-greenville', 'Greenville', 22),
    ('EAST', 'NC', 'North Carolina', 'nc-gastonia', 'Gastonia', 23),
    ('EAST', 'NC', 'North Carolina', 'nc-apex', 'Apex', 24),
    ('EAST', 'NC', 'North Carolina', 'nc-jacksonville', 'Jacksonville', 25),
    ('EAST', 'NC', 'North Carolina', 'nc-chapel-hill', 'Chapel Hill', 26),
    ('EAST', 'NC', 'North Carolina', 'nc-huntersville', 'Huntersville', 27),
    ('EAST', 'NC', 'North Carolina', 'nc-burlington', 'Burlington', 28),
    ('EAST', 'NC', 'North Carolina', 'nc-kannapolis', 'Kannapolis', 29),
    ('EAST', 'NC', 'North Carolina', 'nc-wake-forest', 'Wake Forest', 30),
    ('EAST', 'NC', 'North Carolina', 'nc-rocky-mount', 'Rocky Mount', 31),
    ('EAST', 'NC', 'North Carolina', 'nc-holly-springs', 'Holly Springs', 32),
    ('EAST', 'NC', 'North Carolina', 'nc-wilson', 'Wilson', 33),
    ('EAST', 'NC', 'North Carolina', 'nc-fuquay-varina', 'Fuquay-Varina', 34),
    ('EAST', 'NC', 'North Carolina', 'nc-hickory', 'Hickory', 35),
    ('EAST', 'NC', 'North Carolina', 'nc-goldsboro', 'Goldsboro', 36),
    ('EAST', 'NC', 'North Carolina', 'nc-mooresville', 'Mooresville', 37),
    ('EAST', 'NC', 'North Carolina', 'nc-monroe', 'Monroe', 38),
    ('EAST', 'NC', 'North Carolina', 'nc-salisbury', 'Salisbury', 39),
    ('EAST', 'NC', 'North Carolina', 'nc-southport', 'Southport', 40),
    ('EAST', 'NC', 'North Carolina', 'nc-statesville', 'Statesville', 41),
    ('EAST', 'NC', 'North Carolina', 'nc-sanford', 'Sanford', 42),
    # CA - California 추가 도시
    ('WEST', 'CA', 'California', 'ca-oakland', 'Oakland', 8),
    ('WEST', 'CA', 'California', 'ca-long-beach', 'Long Beach', 9),
    ('WEST', 'CA', 'California', 'ca-fresno', 'Fresno', 10),
    ('WEST', 'CA', 'California', 'ca-bakersfield', 'Bakersfield', 12),
    ('WEST', 'CA', 'California', 'ca-anaheim', 'Anaheim', 13),
    ('WEST', 'CA', 'California', 'ca-santa-ana', 'Santa Ana', 14),
    ('WEST', 'CA', 'California', 'ca-riverside', 'Riverside', 15),
    ('WEST', 'CA', 'California', 'ca-stockton', 'Stockton', 16),
    ('WEST', 'CA', 'California', 'ca-chula-vista', 'Chula Vista', 17),
    # TX - Texas 추가 도시
    ('CENTRAL', 'TX', 'Texas', 'tx-houston', 'Houston', 2),
    ('CENTRAL', 'TX', 'Texas', 'tx-san-antonio', 'San Antonio', 3),
    ('CENTRAL', 'TX', 'Texas', 'tx-austin', 'Austin', 4),
    ('CENTRAL', 'TX', 'Texas', 'tx-fort-worth', 'Fort Worth', 5),
    ('CENTRAL', 'TX', 'Texas', 'tx-el-paso', 'El Paso', 6),
    ('CENTRAL', 'TX', 'Texas', 'tx-arlington', 'Arlington', 7),
    ('CENTRAL', 'TX', 'Texas', 'tx-corpus-christi', 'Corpus Christi', 8),
    ('CENTRAL', 'TX', 'Texas', 'tx-plano', 'Plano', 9),
    ('CENTRAL', 'TX', 'Texas', 'tx-laredo', 'Laredo', 10),
    # FL - Florida 추가
    ('EAST', 'FL', 'Florida', 'fl-jacksonville', 'Jacksonville', 7),
    ('EAST', 'FL', 'Florida', 'fl-fort-lauderdale', 'Fort Lauderdale', 8),
    ('EAST', 'FL', 'Florida', 'fl-st-petersburg', 'St. Petersburg', 9),
    ('EAST', 'FL', 'Florida', 'fl-tallahassee', 'Tallahassee', 10),
    ('EAST', 'FL', 'Florida', 'fl-cape-coral', 'Cape Coral', 11),
    # NY - New York 추가
    ('EAST', 'NY', 'New York', 'ny-brooklyn', 'Brooklyn', 2),
    ('EAST', 'NY', 'New York', 'ny-buffalo', 'Buffalo', 3),
    ('EAST', 'NY', 'New York', 'ny-rochester', 'Rochester', 4),
    ('EAST', 'NY', 'New York', 'ny-albany', 'Albany', 5),
    ('EAST', 'NY', 'New York', 'ny-syracuse', 'Syracuse', 6),
    # GA - Georgia 추가
    ('EAST', 'GA', 'Georgia', 'ga-augusta', 'Augusta', 3),
    ('EAST', 'GA', 'Georgia', 'ga-columbus', 'Columbus', 4),
    ('EAST', 'GA', 'Georgia', 'ga-macon', 'Macon', 5),
    # NJ - New Jersey 추가
    ('EAST', 'NJ', 'New Jersey', 'nj-newark', 'Newark', 3),
    ('EAST', 'NJ', 'New Jersey', 'nj-jersey-city', 'Jersey City', 4),
    ('EAST', 'NJ', 'New Jersey', 'nj-paterson', 'Paterson', 5),
    # IL - Illinois 추가
    ('CENTRAL', 'IL', 'Illinois', 'il-aurora', 'Aurora', 3),
    ('CENTRAL', 'IL', 'Illinois', 'il-naperville', 'Naperville', 4),
    ('CENTRAL', 'IL', 'Illinois', 'il-joliet', 'Joliet', 5),
    ('CENTRAL', 'IL', 'Illinois', 'il-rockford', 'Rockford', 6),
    # OH - Ohio 추가
    ('CENTRAL', 'OH', 'Ohio', 'oh-cincinnati', 'Cincinnati', 3),
    ('CENTRAL', 'OH', 'Ohio', 'oh-toledo', 'Toledo', 4),
    ('CENTRAL', 'OH', 'Ohio', 'oh-akron', 'Akron', 5),
    # AZ - Arizona 추가
    ('WEST', 'AZ', 'Arizona', 'az-tucson', 'Tucson', 2),
    ('WEST', 'AZ', 'Arizona', 'az-mesa', 'Mesa', 3),
    ('WEST', 'AZ', 'Arizona', 'az-chandler', 'Chandler', 4),
    ('WEST', 'AZ', 'Arizona', 'az-scottsdale', 'Scottsdale', 5),
    # WA - Washington 추가
    ('WEST', 'WA', 'Washington', 'wa-spokane', 'Spokane', 2),
    ('WEST', 'WA', 'Washington', 'wa-tacoma', 'Tacoma', 3),
    ('WEST', 'WA', 'Washington', 'wa-vancouver', 'Vancouver', 4),
    # CO - Colorado 추가
    ('WEST', 'CO', 'Colorado', 'co-denver', 'Denver', 2),
    ('WEST', 'CO', 'Colorado', 'co-boulder', 'Boulder', 3),
    # NV - Nevada 추가
    ('WEST', 'NV', 'Nevada', 'nv-reno', 'Reno', 2),
    # OR - Oregon 추가
    ('WEST', 'OR', 'Oregon', 'or-eugene', 'Eugene', 2),
    ('WEST', 'OR', 'Oregon', 'or-salem', 'Salem', 3),
]


def add_cities(apps, schema_editor):
    Region = apps.get_model('community', 'Region')
    Area = apps.get_model('community', 'Area')
    region_map = {r.code: r for r in Region.objects.all()}
    for reg_code, state_code, state_name, slug, city_name, order in EXTRA_CITIES:
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


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('community', '0002_seed_regions_areas_categories')]
    operations = [migrations.RunPython(add_cities, noop)]
