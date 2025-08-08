import logging
import os

from binance_common.configuration import ConfigurationRestAPI
from binance_common.constants import SPOT_REST_API_TESTNET_URL
from binance_sdk_spot import Spot
from binance_sdk_spot.rest_api.models import KlinesIntervalEnum
from dotenv import load_dotenv


def init_spot_client():
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    # load .env file
    load_dotenv()
    # Create configuration for the REST API
    configuration_rest_api = ConfigurationRestAPI(
        api_key=os.getenv("binanceAPIKey"),
        api_secret=os.getenv("binancePrivateKey"),
        base_path=os.getenv("BASE_PATH", SPOT_REST_API_TESTNET_URL),
        timeout=10000,
        backoff=1,  # 当前的官方版本有bug，我门必须改成seconds才能避免卡死问题。
    )

    # Initialize Spot client
    client = Spot(config_rest_api=configuration_rest_api)

    return client


def test_ping():
    client = init_spot_client()
    try:
        response = client.rest_api.ping()

        rate_limits = response.rate_limits
        logging.info(f"ping() rate limits: {rate_limits}")

        data = response.data()
        logging.info(f"ping() response: {data}")
    except Exception as e:
        logging.error(f"ping() error: {e}")


def test_time():
    client = init_spot_client()
    try:
        response = client.rest_api.time()

        rate_limits = response.rate_limits
        logging.info(f"time() rate limits: {rate_limits}")

        data = response.data()
        logging.info(f"time() response: {data}")
    except Exception as e:
        logging.error(f"time() error: {e}")


def test_klines():
    client = init_spot_client()
    try:
        response = client.rest_api.klines(
            symbol="BTCUSDT",
            interval=KlinesIntervalEnum["INTERVAL_1h"].value,
            limit=5,
        )

        rate_limits = response.rate_limits
        logging.info(f"klines() rate limits: {rate_limits}")

        data = response.data()
        logging.info(f"klines() response: {data}")
    except Exception as e:
        logging.error(f"klines() error: {e}")
