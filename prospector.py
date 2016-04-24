import logging
import os

try:
    from functools import lru_cache
except ImportError:
    from backports.functools_lru_cache import lru_cache

import eveapi
import requests

from basil_common.configurables import verify
from basil.market.prospect import prospect as prospects
from basil.industry import IndustryException


LOG = logging.getLogger(__name__)
logging.getLogger('requests').level = logging.WARNING

REQUIRED_OPS = ['REDIS_HOST', 'EVE_API_KEY', 'EVE_API_VCODE', 'REFAPI_URL',
                'STATION_IDS', 'PRICES_URL', 'WATCHES_URL']


def grouped_prints(auth, character_key=False):
    if character_key:
        path = auth.char
    else:
        path = auth.corp
    prints = path.Blueprints().blueprints
    keys = prints.Select('typeID')
    grouped = prints.GroupedBy('typeID')
    return keys, grouped


def collected_prints(auth, character_key=False):
    if character_key:
        path = auth.char
    else:
        path = auth.corp
    prints = path.Blueprints().blueprints
    keys = prints.Select('typeID')
    grouped = prints.GroupedBy('typeID')
    return list(keys), grouped


def blueprint_from(bp, recipe):
    blueprint = {k: bp[k] for k in bp._cols}
    blueprint.update(recipe)
    return blueprint


def evaluate_prospects(refapi, facilities, print_keys, print_groups):
    best_prospects = []
    for key in set(print_keys):
        product = print_groups[key]
        result = evaluate_product(refapi, facilities, product)
        if not result:
            continue
        best_prospects.append(result)
    return best_prospects


def evaluate_product(refapi, facilities, product):
    material_efficiencies = set(product.Select('materialEfficiency'))
    copies_by_me = product.GroupedBy('materialEfficiency')
    for me_value in material_efficiencies:
        # don't evaluate un-researched prints
        if me_value > 3:
            copies = len(copies_by_me[me_value])
            bp = copies_by_me[me_value][0]
            try:
                recipe = refapi('recipes/manufacturing/%s' % bp.typeID)
            except ValueError:
                LOG.warning('ValueError manufacturing bp %s', bp.typeID)
                continue
            blueprint = blueprint_from(bp, recipe)
            try:
                this_prospect = prospects(blueprint, facilities, 1, copies)
            except IndustryException:
                return None
            if this_prospect[0].profit_margin > 5.0:
                return this_prospect
            else:
                # not worth our time, skip it and the rest
                break


def link_refapi(base_url, session):
    @lru_cache(maxsize=32)
    def refapi(url_path, **kwargs):
        url = base_url + url_path
        return session.get(url, **kwargs).json()

    return refapi


def filter_by_quality(output):
    passing = [i[0] for i in output if len(i) > 0 and
               i[0].profit_per_run > 45000]
    passing.sort(key=lambda prosp: prosp.profit_per_unit, reverse=True)
    return passing


def authorized_api():
    api = eveapi.EVEAPIConnection()
    auth = api.auth(keyID=os.environ['EVE_API_KEY'],
                    vCode=os.environ['EVE_API_VCODE'])
    return auth


def as_dict(results):
    import locale
    locale.setlocale( locale.LC_ALL, '' )


    options = []
    for prospect in results:
        opt = {'product': prospect.product,
               'copies': prospect.count,
               'location': prospect.facility.name.split(' ', 1),
               'blueprint_me': prospect.blueprint_me,
               'isk_per_hour': locale.currency(prospect.isk_per_hour),
               'price': locale.currency(prospect.price_per_unit),
               'cost': locale.currency(prospect.cost_per_unit),
               'value': locale.currency(prospect.product_value),
               'profit': locale.currency(prospect.profit_per_unit),
               'margin': "{0:.2f}%".format(prospect.profit_margin),
               'install': locale.currency(prospect.install_cost),
               'materials': prospect.materials.as_dict()}
        options.append(opt)

    return options


def lookup_facilities():
    from basil.industry.facility import facility
    stations = os.environ['STATION_IDS'].split(',')
    return [facility(fac_id) for fac_id in stations]


def main():
    verify(REQUIRED_OPS)

    auth = authorized_api()

    headers = {'user-agent': 'github/eve-basil/prospector/0.1.0-dev'}
    session = requests.Session()
    session.headers.update(headers)

    import basil.market
    basil.market.SESSION = session

    import distutils
    use_char_key = distutils.util.strtobool(
        os.environ.get('USE_CHAR_KEY', False))

    prints_keys, prints_groups = grouped_prints(auth, use_char_key)
    refapi = link_refapi(os.environ['REFAPI_URL'], session)
    evaluation = evaluate_prospects(refapi, lookup_facilities(), prints_keys,
                                    prints_groups)
    best_prospects = as_dict(filter_by_quality(evaluation))

    fields = ['product', 'profit', 'price', 'cost', 'margin']
    import csv
    prospects_file = os.environ.get('OUTPUT_PATH', 'prospects.csv')
    with open(prospects_file, 'w') as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fields,
                                extrasaction='ignore')

        writer.writeheader()
        writer.writerows(best_prospects)

    # import json
    # print json.dumps(best_prospects, indent=2)


if __name__ == "__main__":
    main()
