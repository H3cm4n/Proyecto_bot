"""
services/clob_client.py
Cliente de ejecución real para la creación y firma de órdenes limitadas en el CLOB de Polymarket sobre Polygon.
"""

import os
import sys

# Carga nativa de .env sin dependencia estricta de python-dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    if os.path.exists(".env"):
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, OrderType
    PY_CLOB_AVAILABLE = True
except ImportError:
    PY_CLOB_AVAILABLE = False


class PolymarketClobClient:
    def __init__(self):
        self.private_key = os.getenv("POLYGON_PRIVATE_KEY") or os.getenv("POLYMARKET_PRIVATE_KEY")
        self.api_key = os.getenv("POLYMARKET_API_KEY")
        self.api_secret = os.getenv("POLYMARKET_API_SECRET")
        self.api_passphrase = os.getenv("POLYMARKET_API_PASSPHRASE")
        self.chain_id = int(os.getenv("CHAIN_ID", os.getenv("POLYMARKET_CHAIN_ID", 137)))
        self.host = os.getenv("HOST", os.getenv("POLYMARKET_CLOB_API_URL", "https://clob.polymarket.com"))

        self.client = None
        self._initialize_client()

    def _initialize_client(self):
         if not PY_CLOB_AVAILABLE:
             sys.stderr.write("[CLOB] `py-clob-client` no está instalado en el sistema.\n")
             return

         raw_key = (self.private_key or "").strip()
        
         # Remover prefijo 0x si existe
         if raw_key.startswith("0x") or raw_key.startswith("0X"):
             raw_key = raw_key[2:]

         # Validar si es una cadena hexadecimal pura de 64 caracteres
         is_valid_hex = len(raw_key) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw_key)

         if not is_valid_hex:
             sys.stderr.write("[CLOB] Clave privada no configurada o formato hexadecimal invalido en .env\n")
             return

         try:
             self.client = ClobClient(
                 host=self.host,
                 key=raw_key,
                 chain_id=self.chain_id,
                 creds={
                     "key": self.api_key,
                     "secret": self.api_secret,
                     "passphrase": self.api_passphrase,
                 }
             )
             sys.stderr.write("[CLOB] Cliente Web3 inicializado y listo.\n")
         except Exception as e:
             sys.stderr.write(f"[CLOB] Error al inicializar ClobClient: {e}\n")

    def submit_limit_order(self, token_id: str, price: float, size: float, side: str = "BUY") -> dict:
        if not self.client:
            return {
                "status": "FAILED",
                "reason": "CLIENT_NOT_INITIALIZED (Configura credenciales en .env)"
            }

        try:
            order_args = OrderArgs(
                price=price,
                size=size,
                side=side.upper(),
                token_id=token_id
            )
            signed_order = self.client.create_order(order_args)
            resp = self.client.post_order(signed_order, OrderType.GTC)

            return {
                "status": "SUBMITTED",
                "order_id": resp.get("orderID"),
                "raw_response": resp
            }
        except Exception as e:
            return {
                "status": "FAILED",
                "reason": f"CLOB_SUBMISSION_ERROR ({e})"
            }


if __name__ == "__main__":
    clob = PolymarketClobClient()
    print("[CLOB] Estado del cliente:", "Inicializado correctamente" if clob.client else "Modo de prueba (Faltan credenciales/py-clob-client)")
