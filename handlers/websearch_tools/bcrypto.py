import requests
import re
import logging
import time

# Configure logging
logger = logging.getLogger(__name__)

# Binance API base URL
BASE_URL = "https://api.binance.com"

# Networking defaults (prevents hangs)
_DEFAULT_TIMEOUT = 8.0  # seconds
_SESSION = requests.Session()

# Cache exchangeInfo to avoid refetching every query (keeps things fast + less fragile)
_EXCHANGEINFO_CACHE = {"pairs": None, "ts": 0.0}
_EXCHANGEINFO_TTL = 3600.0  # 1 hour


# Ticker mapping dictionary for top 100 cryptocurrencies with variations
TICKER_MAPPING = {
    # Bitcoin
    "bitcoin": "BTCUSDT",
    "btc": "BTCUSDT",
    "BTC": "BTCUSDT",
    "Btc": "BTCUSDT",
    "BTCUSDT": "BTCUSDT",
    "BtcUsdt": "BTCUSDT",
    # Ethereum
    "ethereum": "ETHUSDT",
    "eth": "ETHUSDT",
    "ETH": "ETHUSDT",
    "Eth": "ETHUSDT",
    "ETHUSDT": "ETHUSDT",
    "EthUsdt": "ETHUSDT",
    # Tether  (NOTE: USDTUSDT is not a real market; we handle USDT in code now)
    "tether": "USDTUSDT",
    "usdt": "USDTUSDT",
    "USDT": "USDTUSDT",
    "Usdt": "USDTUSDT",
    "USDTUSDT": "USDTUSDT",
    "UsdtUsdt": "USDTUSDT",
    # XRP
    "xrp": "XRPUSDT",
    "XRP": "XRPUSDT",
    "Xrp": "XRPUSDT",
    "ripple": "XRPUSDT",
    "Ripple": "XRPUSDT",
    "XRPUSDT": "XRPUSDT",
    "XrpUsdt": "XRPUSDT",
    # BNB
    "bnb": "BNBUSDT",
    "BNB": "BNBUSDT",
    "Bnb": "BNBUSDT",
    "binance coin": "BNBUSDT",
    "Binance Coin": "BNBUSDT",
    "BNBUSDT": "BNBUSDT",
    "BnbUsdt": "BNBUSDT",
    # Solana
    "sol": "SOLUSDT",
    "SOL": "SOLUSDT",
    "Sol": "SOLUSDT",
    "solana": "SOLUSDT",
    "Solana": "SOLUSDT",
    "SOLUSDT": "SOLUSDT",
    "SolUsdt": "SOLUSDT",
    # USDC
    "usdc": "USDCUSDT",
    "USDC": "USDCUSDT",
    "Usdc": "USDCUSDT",
    "usd coin": "USDCUSDT",
    "USD Coin": "USDCUSDT",
    "USDCUSDT": "USDCUSDT",
    "UsdcUsdt": "USDCUSDT",
    # Dogecoin
    "doge": "DOGEUSDT",
    "DOGE": "DOGEUSDT",
    "Doge": "DOGEUSDT",
    "dogecoin": "DOGEUSDT",
    "Dogecoin": "DOGEUSDT",
    "DOGEUSDT": "DOGEUSDT",
    "DogeUsdt": "DOGEUSDT",
    # Cardano
    "ada": "ADAUSDT",
    "ADA": "ADAUSDT",
    "Ada": "ADAUSDT",
    "cardano": "ADAUSDT",
    "Cardano": "ADAUSDT",
    "ADAUSDT": "ADAUSDT",
    "AdaUsdt": "ADAUSDT",
    # TRON
    "trx": "TRXUSDT",
    "TRX": "TRXUSDT",
    "Trx": "TRXUSDT",
    "tron": "TRXUSDT",
    "Tron": "TRXUSDT",
    "TRXUSDT": "TRXUSDT",
    "TrxUsdt": "TRXUSDT",
    # Lido Staked Ether
    "steth": "STETHUSDT",
    "STETH": "STETHUSDT",
    "Steth": "STETHUSDT",
    "lido staked ether": "STETHUSDT",
    "Lido Staked Ether": "STETHUSDT",
    "STETHUSDT": "STETHUSDT",
    "StethUsdt": "STETHUSDT",
    # Wrapped Bitcoin
    "wbtc": "WBTCUSDT",
    "WBTC": "WBTCUSDT",
    "Wbtc": "WBTCUSDT",
    "wrapped bitcoin": "WBTCUSDT",
    "Wrapped Bitcoin": "WBTCUSDT",
    "WBTCUSDT": "WBTCUSDT",
    "WbtcUsdt": "WBTCUSDT",
    # Sui
    "sui": "SUIUSDT",
    "SUI": "SUIUSDT",
    "Sui": "SUIUSDT",
    "SUIUSDT": "SUIUSDT",
    "SuiUsdt": "SUIUSDT",
    # Wrapped stETH
    "wsteth": "WSTETHUSDT",
    "WSTETH": "WSTETHUSDT",
    "Wsteth": "WSTETHUSDT",
    "wrapped steth": "WSTETHUSDT",
    "Wrapped stETH": "WSTETHUSDT",
    "WSTETHUSDT": "WSTETHUSDT",
    "WstethUsdt": "WSTETHUSDT",
    # Chainlink
    "link": "LINKUSDT",
    "LINK": "LINKUSDT",
    "Link": "LINKUSDT",
    "chainlink": "LINKUSDT",
    "Chainlink": "LINKUSDT",
    "LINKUSDT": "LINKUSDT",
    "LinkUsdt": "LINKUSDT",
    # Avalanche
    "avax": "AVAXUSDT",
    "AVAX": "AVAXUSDT",
    "Avax": "AVAXUSDT",
    "avalanche": "AVAXUSDT",
    "Avalanche": "AVAXUSDT",
    "AVAXUSDT": "AVAXUSDT",
    "AvaxUsdt": "AVAXUSDT",
    # Stellar
    "xlm": "XLMUSDT",
    "XLM": "XLMUSDT",
    "Xlm": "XLMUSDT",
    "stellar": "XLMUSDT",
    "Stellar": "XLMUSDT",
    "XLMUSDT": "XLMUSDT",
    "XlmUsdt": "XLMUSDT",
    # Hyperliquid
    "hype": "HYPEUSDT",
    "HYPE": "HYPEUSDT",
    "Hype": "HYPEUSDT",
    "hyperliquid": "HYPEUSDT",
    "Hyperliquid": "HYPEUSDT",
    "HYPEUSDT": "HYPEUSDT",
    "HypeUsdt": "HYPEUSDT",
    # Shiba Inu
    "shib": "SHIBUSDT",
    "SHIB": "SHIBUSDT",
    "Shib": "SHIBUSDT",
    "shiba inu": "SHIBUSDT",
    "Shiba Inu": "SHIBUSDT",
    "SHIBUSDT": "SHIBUSDT",
    "ShibUsdt": "SHIBUSDT",
    # Hedera
    "hbar": "HBARUSDT",
    "HBAR": "HBARUSDT",
    "Hbar": "HBARUSDT",
    "hedera": "HBARUSDT",
    "Hedera": "HBARUSDT",
    "HBARUSDT": "HBARUSDT",
    "HbarUsdt": "HBARUSDT",
    # LEO Token
    "leo": "LEOUSDT",
    "LEO": "LEOUSDT",
    "Leo": "LEOUSDT",
    "leo token": "LEOUSDT",
    "LEO Token": "LEOUSDT",
    "LEOUSDT": "LEOUSDT",
    "LeoUsdt": "LEOUSDT",
    # Bitcoin Cash
    "bch": "BCHUSDT",
    "BCH": "BCHUSDT",
    "Bch": "BCHUSDT",
    "bitcoin cash": "BCHUSDT",
    "Bitcoin Cash": "BCHUSDT",
    "BCHUSDT": "BCHUSDT",
    "BchUsdt": "BCHUSDT",
    # Toncoin
    "ton": "TONUSDT",
    "TON": "TONUSDT",
    "Ton": "TONUSDT",
    "toncoin": "TONUSDT",
    "Toncoin": "TONUSDT",
    "TONUSDT": "TONUSDT",
    "TonUsdt": "TONUSDT",
    # Litecoin
    "ltc": "LTCUSDT",
    "LTC": "LTCUSDT",
    "Ltc": "LTCUSDT",
    "litecoin": "LTCUSDT",
    "Litecoin": "LTCUSDT",
    "LTCUSDT": "LTCUSDT",
    "LtcUsdt": "LTCUSDT",
    # Polkadot
    "dot": "DOTUSDT",
    "DOT": "DOTUSDT",
    "Dot": "DOTUSDT",
    "polkadot": "DOTUSDT",
    "Polkadot": "DOTUSDT",
    "DOTUSDT": "DOTUSDT",
    "DotUsdt": "DOTUSDT",
    # WETH
    "weth": "WETHUSDT",
    "WETH": "WETHUSDT",
    "Weth": "WETHUSDT",
    "WETHUSDT": "WETHUSDT",
    "WethUsdt": "WETHUSDT",
    # USDS
    "usds": "USDSUSDT",
    "USDS": "USDSUSDT",
    "Usds": "USDSUSDT",
    "USDSUSDT": "USDSUSDT",
    "UsdsUsdt": "USDSUSDT",
    # Monero
    "xmr": "XMRUSDT",
    "XMR": "XMRUSDT",
    "Xmr": "XMRUSDT",
    "monero": "XMRUSDT",
    "Monero": "XMRUSDT",
    "XMRUSDT": "XMRUSDT",
    "XmrUsdt": "XMRUSDT",
    # Wrapped eETH
    "weeth": "WEETHUSDT",
    "WEETH": "WEETHUSDT",
    "Weeth": "WEETHUSDT",
    "wrapped eeth": "WEETHUSDT",
    "Wrapped eETH": "WEETHUSDT",
    "WEETHUSDT": "WEETHUSDT",
    "WeethUsdt": "WEETHUSDT",
    # Bitget Token
    "bgb": "BGBUSDT",
    "BGB": "BGBUSDT",
    "Bgb": "BGBUSDT",
    "bitget token": "BGBUSDT",
    "Bitget Token": "BGBUSDT",
    "BGBUSDT": "BGBUSDT",
    "BgbUsdt": "BGBUSDT",
    # Binance Bridged USDT
    "bsc-usd": "BSCUSDUSDT",
    "BSC-USD": "BSCUSDUSDT",
    "Bsc-Usd": "BSCUSDUSDT",
    "binance bridged usdt": "BSCUSDUSDT",
    "Binance Bridged USDT": "BSCUSDUSDT",
    "BSCUSDUSDT": "BSCUSDUSDT",
    "BscUsdUsdt": "BSCUSDUSDT",
    # Pi Network
    "pi": "PIUSDT",
    "PI": "PIUSDT",
    "Pi": "PIUSDT",
    "pi network": "PIUSDT",
    "Pi Network": "PIUSDT",
    "PIUSDT": "PIUSDT",
    "PiUsdt": "PIUSDT",
    # Pepe
    "pepe": "PEPEUSDT",
    "PEPE": "PEPEUSDT",
    "Pepe": "PEPEUSDT",
    "pepe coin": "PEPEUSDT",
    "Pepe Coin": "PEPEUSDT",
    "PEPEUSDT": "PEPEUSDT",
    "PepeUsdt": "PEPEUSDT",
    # Ethena USDe
    "usde": "USDEUSDT",
    "USDE": "USDEUSDT",
    "Usde": "USDEUSDT",
    "ethena usde": "USDEUSDT",
    "Ethena USDe": "USDEUSDT",
    "USDEUSDT": "USDEUSDT",
    "UsdeUsdt": "USDEUSDT",
    # Coinbase Wrapped BTC
    "cbbtc": "CBBTCUSDT",
    "CBBTC": "CBBTCUSDT",
    "Cbbtc": "CBBTCUSDT",
    "coinbase wrapped btc": "CBBTCUSDT",
    "Coinbase Wrapped BTC": "CBBTCUSDT",
    "CBBTCUSDT": "CBBTCUSDT",
    "CbbtcUsdt": "CBBTCUSDT",
    # WhiteBIT Coin
    "wbt": "WBTUSDT",
    "WBT": "WBTUSDT",
    "Wbt": "WBTUSDT",
    "whitebit coin": "WBTUSDT",
    "WhiteBIT Coin": "WBTUSDT",
    "WBTUSDT": "WBTUSDT",
    "WbtUsdt": "WBTUSDT",
    # Aave
    "aave": "AAVEUSDT",
    "AAVE": "AAVEUSDT",
    "Aave": "AAVEUSDT",
    "AAVEUSDT": "AAVEUSDT",
    "AaveUsdt": "AAVEUSDT",
    # Uniswap
    "uni": "UNIUSDT",
    "UNI": "UNIUSDT",
    "Uni": "UNIUSDT",
    "uniswap": "UNIUSDT",
    "Uniswap": "UNIUSDT",
    "UNIUSDT": "UNIUSDT",
    "UniUsdt": "UNIUSDT",
    # Bittensor
    "tao": "TAOUSDT",
    "TAO": "TAOUSDT",
    "Tao": "TAOUSDT",
    "bittensor": "TAOUSDT",
    "Bittensor": "TAOUSDT",
    "TAOUSDT": "TAOUSDT",
    "TaoUsdt": "TAOUSDT",
    # Dai
    "dai": "DAIUSDT",
    "DAI": "DAIUSDT",
    "Dai": "DAIUSDT",
    "DAIUSDT": "DAIUSDT",
    "DaiUsdt": "DAIUSDT",
    # NEAR Protocol
    "near": "NEARUSDT",
    "NEAR": "NEARUSDT",
    "Near": "NEARUSDT",
    "near protocol": "NEARUSDT",
    "NEAR Protocol": "NEARUSDT",
    "NEARUSDT": "NEARUSDT",
    "NearUsdt": "NEARUSDT",
    # Aptos
    "apt": "APTUSDT",
    "APT": "APTUSDT",
    "Apt": "APTUSDT",
    "aptos": "APTUSDT",
    "Aptos": "APTUSDT",
    "APTUSDT": "APTUSDT",
    "AptUsdt": "APTUSDT",
    # OKB
    "okb": "OKBUSDT",
    "OKB": "OKBUSDT",
    "Okb": "OKBUSDT",
    "OKBUSDT": "OKBUSDT",
    "OkbUsdt": "OKBUSDT",
    # Jito Staked SOL
    "jitosol": "JITOSOLUSDT",
    "JITOSOL": "JITOSOLUSDT",
    "Jitosol": "JITOSOLUSDT",
    "jito staked sol": "JITOSOLUSDT",
    "Jito Staked SOL": "JITOSOLUSDT",
    "JITOSOLUSDT": "JITOSOLUSDT",
    "JitosolUsdt": "JITOSOLUSDT",
    # Ondo
    "ondo": "ONDOUSDT",
    "ONDO": "ONDOUSDT",
    "Ondo": "ONDOUSDT",
    "ONDOUSDT": "ONDOUSDT",
    "OndoUsdt": "ONDOUSDT",
    # Kaspa
    "kas": "KASUSDT",
    "KAS": "KASUSDT",
    "Kas": "KASUSDT",
    "kaspa": "KASUSDT",
    "Kaspa": "KASUSDT",
    "KASUSDT": "KASUSDT",
    "KasUsdt": "KASUSDT",
    # Official Trump
    "trump": "TRUMPUSDT",
    "TRUMP": "TRUMPUSDT",
    "Trump": "TRUMPUSDT",
    "official trump": "TRUMPUSDT",
    "Official Trump": "TRUMPUSDT",
    "TRUMPUSDT": "TRUMPUSDT",
    "TrumpUsdt": "TRUMPUSDT",
    # Cronos
    "cro": "CROUSDT",
    "CRO": "CROUSDT",
    "Cro": "CROUSDT",
    "cronos": "CROUSDT",
    "Cronos": "CROUSDT",
    "CROUSDT": "CROUSDT",
    "CroUsdt": "CROUSDT",
    # BlackRock USD Institutional Digital Liquidity Fund
    "buidl": "BUIDLUSDT",
    "BUIDL": "BUIDLUSDT",
    "Buidl": "BUIDLUSDT",
    "blackrock usd institutional digital liquidity fund": "BUIDLUSDT",
    "BlackRock USD Institutional Digital Liquidity Fund": "BUIDLUSDT",
    "BUIDLUSDT": "BUIDLUSDT",
    "BuidlUsdt": "BUIDLUSDT",
    # Tokenize Xchange
    "tkx": "TKXUSDT",
    "TKX": "TKXUSDT",
    "Tkx": "TKXUSDT",
    "tokenize xchange": "TKXUSDT",
    "Tokenize Xchange": "TKXUSDT",
    "TKXUSDT": "TKXUSDT",
    "TkxUsdt": "TKXUSDT",
    # Ethereum Classic
    "etc": "ETCUSDT",
    "ETC": "ETCUSDT",
    "Etc": "ETCUSDT",
    "ethereum classic": "ETCUSDT",
    "Ethereum Classic": "ETCUSDT",
    "ETCUSDT": "ETCUSDT",
    "EtcUsdt": "ETCUSDT",
    # Internet Computer
    "icp": "ICPUSDT",
    "ICP": "ICPUSDT",
    "Icp": "ICPUSDT",
    "internet computer": "ICPUSDT",
    "Internet Computer": "ICPUSDT",
    "ICPUSDT": "ICPUSDT",
    "IcpUsdt": "ICPUSDT",
    # Gate
    "gt": "GTUSDT",
    "GT": "GTUSDT",
    "Gt": "GTUSDT",
    "gate": "GTUSDT",
    "Gate": "GTUSDT",
    "GTUSDT": "GTUSDT",
    "GtUsdt": "GTUSDT",
    # Ethena Staked USDe
    "susde": "SUSDEUSDT",
    "SUSDE": "SUSDEUSDT",
    "Susde": "SUSDEUSDT",
    "ethena staked usde": "SUSDEUSDT",
    "Ethena Staked USDe": "SUSDEUSDT",
    "SUSDEUSDT": "SUSDEUSDT",
    "SusdeUsdt": "SUSDEUSDT",
    # VeChain
    "vet": "VETUSDT",
    "VET": "VETUSDT",
    "Vet": "VETUSDT",
    "vechain": "VETUSDT",
    "VeChain": "VETUSDT",
    "VETUSDT": "VETUSDT",
    "VetUsdt": "VETUSDT",
    # Mantle
    "mnt": "MNTUSDT",
    "MNT": "MNTUSDT",
    "Mnt": "MNTUSDT",
    "mantle": "MNTUSDT",
    "Mantle": "MNTUSDT",
    "MNTUSDT": "MNTUSDT",
    "MntUsdt": "MNTUSDT",
    # Render
    "render": "RENDERUSDT",
    "RENDER": "RENDERUSDT",
    "Render": "RENDERUSDT",
    "RENDERUSDT": "RENDERUSDT",
    "RenderUsdt": "RENDERUSDT",
    # sUSDS
    "susds": "SUSDSUSDT",
    "SUSDS": "SUSDSUSDT",
    "Susds": "SUSDSUSDT",
    "SUSDSUSDT": "SUSDSUSDT",
    "SusdsUsdt": "SUSDSUSDT",
    # Ethena
    "ena": "ENAUSDT",
    "ENA": "ENAUSDT",
    "Ena": "ENAUSDT",
    "ethena": "ENAUSDT",
    "Ethena": "ENAUSDT",
    "ENAUSDT": "ENAUSDT",
    "EnaUsdt": "ENAUSDT",
    # Cosmos Hub
    "atom": "ATOMUSDT",
    "ATOM": "ATOMUSDT",
    "Atom": "ATOMUSDT",
    "cosmos hub": "ATOMUSDT",
    "Cosmos Hub": "ATOMUSDT",
    "ATOMUSDT": "ATOMUSDT",
    "AtomUsdt": "ATOMUSDT",
    # USD1
    "usd1": "USD1USDT",
    "USD1": "USD1USDT",
    "Usd1": "USD1USDT",
    "USD1USDT": "USD1USDT",
    "Usd1Usdt": "USD1USDT",
    # Lombard Staked BTC
    "lbtc": "LBTCUSDT",
    "LBTC": "LBTCUSDT",
    "Lbtc": "LBTCUSDT",
    "lombard staked btc": "LBTCUSDT",
    "Lombard Staked BTC": "LBTCUSDT",
    "LBTCUSDT": "LBTCUSDT",
    "LbtcUsdt": "LBTCUSDT",
    # POL (ex-MATIC)
    "pol": "POLUSDT",
    "POL": "POLUSDT",
    "Pol": "POLUSDT",
    "pol (ex-matic)": "POLUSDT",
    "POL (ex-MATIC)": "POLUSDT",
    "matic": "POLUSDT",  # Alias for previous name
    "MATIC": "POLUSDT",
    "Matic": "POLUSDT",
    "polygon": "POLUSDT",
    "Polygon": "POLUSDT",
    "POLUSDT": "POLUSDT",
    "PolUsdt": "POLUSDT",
    # Artificial Superintelligence Alliance
    "fet": "FETUSDT",
    "FET": "FETUSDT",
    "Fet": "FETUSDT",
    "artificial superintelligence alliance": "FETUSDT",
    "Artificial Superintelligence Alliance": "FETUSDT",
    "FETUSDT": "FETUSDT",
    "FetUsdt": "FETUSDT",
    # Algorand
    "algo": "ALGOUSDT",
    "ALGO": "ALGOUSDT",
    "Algo": "ALGOUSDT",
    "algorand": "ALGOUSDT",
    "Algorand": "ALGOUSDT",
    "ALGOUSDT": "ALGOUSDT",
    "AlgoUsdt": "ALGOUSDT",
    # Arbitrum
    "arb": "ARBUSDT",
    "ARB": "ARBUSDT",
    "Arb": "ARBUSDT",
    "arbitrum": "ARBUSDT",
    "Arbitrum": "ARBUSDT",
    "ARBUSDT": "ARBUSDT",
    "ArbUsdt": "ARBUSDT",
    # Filecoin
    "fil": "FILUSDT",
    "FIL": "FILUSDT",
    "Fil": "FILUSDT",
    "filecoin": "FILUSDT",
    "Filecoin": "FILUSDT",
    "FILUSDT": "FILUSDT",
    "FilUsdt": "FILUSDT",
    # Fasttoken
    "ftn": "FTNUSDT",
    "FTN": "FTNUSDT",
    "Ftn": "FTNUSDT",
    "fasttoken": "FTNUSDT",
    "Fasttoken": "FTNUSDT",
    "FTNUSDT": "FTNUSDT",
    "FtnUsdt": "FTNUSDT",
    # Worldcoin
    "wld": "WLDUSDT",
    "WLD": "WLDUSDT",
    "Wld": "WLDUSDT",
    "worldcoin": "WLDUSDT",
    "Worldcoin": "WLDUSDT",
    "WLDUSDT": "WLDUSDT",
    "WldUsdt": "WLDUSDT",
    # Celestia
    "tia": "TIAUSDT",
    "TIA": "TIAUSDT",
    "Tia": "TIAUSDT",
    "celestia": "TIAUSDT",
    "Celestia": "TIAUSDT",
    "TIAUSDT": "TIAUSDT",
    "TiaUsdt": "TIAUSDT",
    # Sonic (prev. FTM)
    "s": "SUSDT",
    "S": "SUSDT",
    "s": "SUSDT",
    "sonic": "SUSDT",
    "Sonic": "SUSDT",
    "sonic (prev. ftm)": "SUSDT",
    "ftm": "SUSDT",  # Alias for previous name
    "FTM": "SUSDT",
    "Ftm": "SUSDT",
    "SUSDT": "SUSDT",
    "SUsdt": "SUSDT",
    # Jupiter Perpetuals Liquidity Provider Token
    "jlp": "JLPUSDT",
    "JLP": "JLPUSDT",
    "Jlp": "JLPUSDT",
    "jupiter perpetuals liquidity provider token": "JLPUSDT",
    "Jupiter Perpetuals Liquidity Provider Token": "JLPUSDT",
    "JLPUSDT": "JLPUSDT",
    "JlpUsdt": "JLPUSDT",
    # Bonk
    "bonk": "BONKUSDT",
    "BONK": "BONKUSDT",
    "Bonk": "BONKUSDT",
    "BONKUSDT": "BONKUSDT",
    "BonkUsdt": "BONKUSDT",
    # First Digital USD
    "fdusd": "FDUSDUSDT",
    "FDUSD": "FDUSDUSDT",
    "Fdusd": "FDUSDUSDT",
    "first digital usd": "FDUSDUSDT",
    "First Digital USD": "FDUSDUSDT",
    "FDUSDUSDT": "FDUSDUSDT",
    "FdusdUsdt": "FDUSDUSDT",
    # Jupiter
    "jup": "JUPUSDT",
    "JUP": "JUPUSDT",
    "Jup": "JUPUSDT",
    "jupiter": "JUPUSDT",
    "Jupiter": "JUPUSDT",
    "JUPUSDT": "JUPUSDT",
    "JupUsdt": "JUPUSDT",
    # Binance-Peg WETH
    "binance-peg weth": "WETHUSDT",
    "Binance-Peg WETH": "WETHUSDT",
    "WETHUSDT": "WETHUSDT",
    "WethUsdt": "WETHUSDT",
    # Binance Staked SOL
    "bnsol": "BNSOLUSDT",
    "BNSOL": "BNSOLUSDT",
    "Bnsol": "BNSOLUSDT",
    "binance staked sol": "BNSOLUSDT",
    "Binance Staked SOL": "BNSOLUSDT",
    "BNSOLUSDT": "BNSOLUSDT",
    "BnsolUsdt": "BNSOLUSDT",
    # Quant
    "qnt": "QNTUSDT",
    "QNT": "QNTUSDT",
    "Qnt": "QNTUSDT",
    "quant": "QNTUSDT",
    "Quant": "QNTUSDT",
    "QNTUSDT": "QNTUSDT",
    "QntUsdt": "QNTUSDT",
    # KuCoin
    "kcs": "KCSUSDT",
    "KCS": "KCSUSDT",
    "Kcs": "KCSUSDT",
    "kucoin": "KCSUSDT",
    "KuCoin": "KCSUSDT",
    "KCSUSDT": "KCSUSDT",
    "KcsUsdt": "KCSUSDT",
    # Kelp DAO Restaked ETH
    "rseth": "RSETHUSDT",
    "RSETH": "RSETHUSDT",
    "Rseth": "RSETHUSDT",
    "kelp dao restaked eth": "RSETHUSDT",
    "Kelp DAO Restaked ETH": "RSETHUSDT",
    "RSETHUSDT": "RSETHUSDT",
    "RsethUsdt": "RSETHUSDT",
    # Stacks
    "stx": "STXUSDT",
    "STX": "STXUSDT",
    "Stx": "STXUSDT",
    "stacks": "STXUSDT",
    "Stacks": "STXUSDT",
    "STXUSDT": "STXUSDT",
    "StxUsdt": "STXUSDT",
    # Fartcoin
    "fartcoin": "FARTCOINUSDT",
    "FARTCOIN": "FARTCOINUSDT",
    "Fartcoin": "FARTCOINUSDT",
    "FARTCOINUSDT": "FARTCOINUSDT",
    "FartcoinUsdt": "FARTCOINUSDT",
    # Virtuals Protocol
    "virtual": "VIRTUALUSDT",
    "VIRTUAL": "VIRTUALUSDT",
    "Virtual": "VIRTUALUSDT",
    "virtuals protocol": "VIRTUALUSDT",
    "Virtuals Protocol": "VIRTUALUSDT",
    "VIRTUALUSDT": "VIRTUALUSDT",
    "VirtualUsdt": "VIRTUALUSDT",
    # NEXO
    "nexo": "NEXOUSDT",
    "NEXO": "NEXOUSDT",
    "Nexo": "NEXOUSDT",
    "NEXOUSDT": "NEXOUSDT",
    "NexoUsdt": "NEXOUSDT",
    # Story
    "ip": "IPUSDT",
    "IP": "IPUSDT",
    "Ip": "IPUSDT",
    "story": "IPUSDT",
    "Story": "IPUSDT",
    "IPUSDT": "IPUSDT",
    "IpUsdt": "IPUSDT",
    # Flare
    "flr": "FLRUSDT",
    "FLR": "FLRUSDT",
    "Flr": "FLRUSDT",
    "flare": "FLRUSDT",
    "Flare": "FLRUSDT",
    "FLRUSDT": "FLRUSDT",
    "FlrUsdt": "FLRUSDT",
    # Optimism
    "op": "OPUSDT",
    "OP": "OPUSDT",
    "Op": "OPUSDT",
    "optimism": "OPUSDT",
    "Optimism": "OPUSDT",
    "OPUSDT": "OPUSDT",
    "OpUsdt": "OPUSDT",
    # Immutable
    "imx": "IMXUSDT",
    "IMX": "IMXUSDT",
    "Imx": "IMXUSDT",
    "immutable": "IMXUSDT",
    "Immutable": "IMXUSDT",
    "IMXUSDT": "IMXUSDT",
    "ImxUsdt": "IMXUSDT",
    # Sei
    "sei": "SEIUSDT",
    "SEI": "SEIUSDT",
    "Sei": "SEIUSDT",
    "SEIUSDT": "SEIUSDT",
    "SeiUsdt": "SEIUSDT",
    # Rocket Pool ETH
    "reth": "RETHUSDT",
    "RETH": "RETHUSDT",
    "Reth": "RETHUSDT",
    "rocket pool eth": "RETHUSDT",
    "Rocket Pool ETH": "RETHUSDT",
    "RETHUSDT": "RETHUSDT",
    "RethUsdt": "RETHUSDT",
    # Injective
    "inj": "INJUSDT",
    "INJ": "INJUSDT",
    "Inj": "INJUSDT",
    "injective": "INJUSDT",
    "Injective": "INJUSDT",
    "INJUSDT": "INJUSDT",
    "InjUsdt": "INJUSDT",
    # Maker
    "mkr": "MKRUSDT",
    "MKR": "MKRUSDT",
    "Mkr": "MKRUSDT",
    "maker": "MKRUSDT",
    "Maker": "MKRUSDT",
    "MKRUSDT": "MKRUSDT",
    "MkrUsdt": "MKRUSDT",
    # USDT0
    "usdt0": "USDT0USDT",
    "USDT0": "USDT0USDT",
    "Usdt0": "USDT0USDT",
    "USDT0USDT": "USDT0USDT",
    "Usdt0Usdt": "USDT0USDT",
    # EOS
    "eos": "EOSUSDT",
    "EOS": "EOSUSDT",
    "Eos": "EOSUSDT",
    "EOSUSDT": "EOSUSDT",
    "EosUsdt": "EOSUSDT",
    # XDC Network
    "xdc": "XDCUSDT",
    "XDC": "XDCUSDT",
    "Xdc": "XDCUSDT",
    "xdc network": "XDCUSDT",
    "XDC Network": "XDCUSDT",
    "XDCUSDT": "XDCUSDT",
    "XdcUsdt": "XDCUSDT",
    # The Graph
    "grt": "GRTUSDT",
    "GRT": "GRTUSDT",
    "Grt": "GRTUSDT",
    "the graph": "GRTUSDT",
    "The Graph": "GRTUSDT",
    "GRTUSDT": "GRTUSDT",
    "GrtUsdt": "GRTUSDT",
    # dogwifhat
    "wif": "WIFUSDT",
    "WIF": "WIFUSDT",
    "Wif": "WIFUSDT",
    "dogwifhat": "WIFUSDT",
    "Dogwifhat": "WIFUSDT",
    "WIFUSDT": "WIFUSDT",
    "WifUsdt": "WIFUSDT",
    # Solv Protocol BTC
    "solvbtc": "SOLVBTCUSDT",
    "SOLVBTC": "SOLVBTCUSDT",
    "Solvbtc": "SOLVBTCUSDT",
    "solv protocol btc": "SOLVBTCUSDT",
    "Solv Protocol BTC": "SOLVBTCUSDT",
    "SOLVBTCUSDT": "SOLVBTCUSDT",
    "SolvbtcUsdt": "SOLVBTCUSDT",
    # Curve DAO
    "crv": "CRVUSDT",
    "CRV": "CRVUSDT",
    "Crv": "CRVUSDT",
    "curve dao": "CRVUSDT",
    "Curve DAO": "CRVUSDT",
    "CRVUSDT": "CRVUSDT",
    "CrvUsdt": "CRVUSDT",
    # FLOKI
    "floki": "FLOKIUSDT",
    "FLOKI": "FLOKIUSDT",
    "Floki": "FLOKIUSDT",
    "FLOKIUSDT": "FLOKIUSDT",
    "FlokiUsdt": "FLOKIUSDT",
}

def get_binance_pairs(force_refresh: bool = False):
    """Fetch all USDT trading pairs from Binance /exchangeInfo endpoint (cached)."""
    now = time.time()
    if (
        not force_refresh
        and _EXCHANGEINFO_CACHE["pairs"] is not None
        and (now - _EXCHANGEINFO_CACHE["ts"]) < _EXCHANGEINFO_TTL
    ):
        return _EXCHANGEINFO_CACHE["pairs"]

    try:
        url = f"{BASE_URL}/api/v3/exchangeInfo"
        response = _SESSION.get(url, timeout=_DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        usdt_pairs = [
            symbol["symbol"]
            for symbol in data.get("symbols", [])
            if symbol.get("quoteAsset") == "USDT" and symbol.get("status") == "TRADING"
        ]
        logger.debug(f"Fetched {len(usdt_pairs)} USDT trading pairs from Binance")

        _EXCHANGEINFO_CACHE["pairs"] = usdt_pairs
        _EXCHANGEINFO_CACHE["ts"] = now
        return usdt_pairs
    except requests.RequestException as e:
        logger.error(f"Error fetching Binance pairs: {e}")
        return _EXCHANGEINFO_CACHE["pairs"] or []


def verify_binance_support(symbol):
    """Check if a symbol is supported as a USDT pair on Binance.

    If exchangeInfo is temporarily unavailable, return True and let ticker/price
    endpoint be the final validator (fail-open for resilience).
    """
    usdt_pairs = get_binance_pairs()
    if not usdt_pairs:
        logger.warning(
            f"Binance exchangeInfo unavailable while validating '{symbol}'. "
            "Proceeding to direct price lookup."
        )
        return True
    supported = symbol in usdt_pairs
    logger.debug(f"Verifying Binance support for '{symbol}': {'Supported' if supported else 'Not supported'}")
    return supported


def get_crypto_price(crypto_input):
    """Fetch the price of a cryptocurrency from Binance API."""
    raw_input = (crypto_input or "").strip()
    if not raw_input:
        return "Error: empty crypto query."

    # Clean but keep ORIGINAL casing for symbol detection
    cleaned_query = re.sub(
        r"^(whats\s+the\s+price\s+of|what's\s+the\s+price\s+of|price\s+of)\s+",
        "",
        raw_input,
        flags=re.IGNORECASE,
    ).strip()

    logger.debug(f"Processing crypto query raw='{raw_input}' cleaned='{cleaned_query}'")

    # -----------------------------
    # PATCH 1: Stablecoin shortcut
    # -----------------------------
    # Avoid bogus "USDTUSDT"
    if cleaned_query.strip().lower() in ("usdt", "tether"):
        # Return in the exact format FinanceHandler expects
        return "Tether (USDT): $1.00"

    # -----------------------------
    # PATCH 2: Direct symbol fast-path
    # -----------------------------
    # If user passed "BTCUSDT" (any casing), use it directly.
    if re.fullmatch(r"[A-Za-z0-9]{2,20}USDT", cleaned_query):
        symbol = cleaned_query.upper()
        if not verify_binance_support(symbol):
            logger.warning(f"'{raw_input}' ({symbol}) is not supported as a USDT pair on Binance")
            return f"Error: '{raw_input}' ({symbol}) is not supported as a USDT pair on Binance."
        return _fetch_binance_price(symbol, display_name=symbol.replace("USDT", ""))

    # From here on, use lowercased query for mapping + partial-match
    q_lower = cleaned_query.lower().strip()

    symbol = TICKER_MAPPING.get(q_lower) or TICKER_MAPPING.get(cleaned_query)  # allow exact key too
    if symbol:
        logger.debug(f"Exact match found: '{cleaned_query}' -> '{symbol}'")
    else:
        # Partial match: look for mapping keys as words inside the query
        for key in TICKER_MAPPING:
            if re.search(r"\b" + re.escape(key.lower()) + r"\b", q_lower):
                symbol = TICKER_MAPPING[key]
                logger.debug(f"Partial match found: '{key}' in '{cleaned_query}' -> '{symbol}'")
                break
        else:
            logger.warning(f"No match found for '{cleaned_query}' in TICKER_MAPPING")
            return f"Error: '{crypto_input}' not found in ticker mapping."

    # If mapping returned something odd, normalize
    symbol = (symbol or "").upper().strip()

    if not verify_binance_support(symbol):
        logger.warning(f"'{crypto_input}' ({symbol}) is not supported as a USDT pair on Binance")
        return f"Error: '{crypto_input}' ({symbol}) is not supported as a USDT pair on Binance."

    # Display name: try to preserve user-friendly name
    display_name = cleaned_query
    return _fetch_binance_price(symbol, display_name=display_name)


def _fetch_binance_price(symbol: str, display_name: str):
    """Internal helper to fetch Binance price and format output consistently."""
    try:
        url = f"{BASE_URL}/api/v3/ticker/price?symbol={symbol}"
        response = _SESSION.get(url, timeout=_DEFAULT_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        if "price" in data:
            price_val = float(data["price"])
            logger.info(f"Successfully fetched price for '{display_name}' ({symbol}): ${price_val:,.2f}")
            # Keep EXACT format FinanceHandler parses:
            # Name (SYMBOL): $123,456.78
            return f"{str(display_name).title()} ({symbol}): ${price_val:,.2f}"

        logger.error(f"Invalid response for {symbol}: {data}")
        return f"Error: Invalid response for {symbol}: {data}"
    except requests.RequestException as e:
        logger.error(f"Error fetching price for {symbol}: {e}")
        return f"Error fetching price for {symbol}: {e}"


def main():
    logger.info(f"Loaded {len(TICKER_MAPPING)} ticker mappings for cryptocurrencies.")
    while True:
        crypto_input = input("Enter cryptocurrency name/symbol (e.g., Bitcoin, BTC, BTCUSDT) or 'quit' to exit: ")
        if crypto_input.lower() == "quit":
            break
        print(get_crypto_price(crypto_input))


if __name__ == "__main__":
    main()