import toml
import os

# common init
path = f'{os.path.abspath(os.curdir)}/'

try:
    config = toml.load(f'{path}config.toml')
except FileNotFoundError:
    print(f'[CONFIG] config.toml not found!')

    # backup logic to get path for config.py
    import inspect
    class DummyClass:
        pass
    local_dir = os.path.dirname(os.path.abspath(inspect.getsourcefile(DummyClass)))

    try:
        config = toml.load(f'{local_dir}/config.toml')
    except FileNotFoundError:
        print(f'[CONFIG] config.toml not found while searching with inspect.getsourcefile.')
        import sys
        sys.exit(-1)

# config variables
difan = {
    "host": config.get('database').get('server'),
    "user": config.get('database').get('login'),
    "password": config.get('database').get('password')
}

dwh = {
    "host": config.get('database').get('server'),
    "user": config.get('database').get('login'),
    "password": config.get('database').get('password')
}  # alias for difan

hse = {
    "host": config.get('HSE').get('server'),
    "user": config.get('HSE').get('login'),
    "password": config.get('HSE').get('password'),
    "database": 'tickers'  # default db
}

API_HOST = "https://financialmodelingprep.com/api/v3/"
API_HOST_v3 = "https://financialmodelingprep.com/api/v3/"
API_HOST_v4 = "https://financialmodelingprep.com/api/v4/"
API_KEY = config.get('financialmodelingprep').get('api_key')

EOD_HOST = "https://eodhistoricaldata.com/api/"
EOD_KEY = config.get('EODHD').get('api_key')

