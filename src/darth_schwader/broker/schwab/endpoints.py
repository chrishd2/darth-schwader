from __future__ import annotations

BASE_URL = "https://api.schwabapi.com"
OAUTH_AUTHORIZE_URL = f"{BASE_URL}/v1/oauth/authorize"
OAUTH_TOKEN_URL = f"{BASE_URL}/v1/oauth/token"
ACCOUNTS_URL = f"{BASE_URL}/trader/v1/accounts"
POSITIONS_URL = f"{BASE_URL}/trader/v1/accounts/{{account_id}}"
OPTION_CHAINS_URL = f"{BASE_URL}/marketdata/v1/chains"
ORDERS_URL = f"{BASE_URL}/trader/v1/accounts/{{account_id}}/orders"
ORDER_URL = f"{BASE_URL}/trader/v1/accounts/{{account_id}}/orders/{{order_id}}"
