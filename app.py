from flask import Flask, url_for
from flask import request
from flask import render_template
from flask import flash
import pandas as pd
import numpy as np
import cbpro
import mysql.connector as mc
import requests
import re

app=Flask(__name__)


def get_prices():
    r1 = requests.get('https://coinmarketcap.com/currencies/bitcoin/historical-data/')
    btc_content = r1.text
    r2 = requests.get('https://coinmarketcap.com/currencies/ethereum/historical-data/')
    eth_content = r2.text
    r3 = requests.get('https://coinmarketcap.com/currencies/litecoin/historical-data/')
    ltc_content = r3.text

    res1 = re.search('"price":.*?(\d+).*",', btc_content)
    res2 = re.search('"price":.*?(\d+).*",', eth_content)
    res3 = re.search('"price":.*?(\d+).*",', ltc_content)

    btc_price = res1.group(0).strip().split('"')[3]
    eth_price = res2.group(0).strip().split('"')[3]
    ltc_price = res3.group(0).strip().split('"')[3]

    

    return btc_price,eth_price,ltc_price



def create_symbol_table():
    return pd.DataFrame({"symbol": ["BTC", "ETH", "LTC"]})


def create_transaction_table():
    return pd.DataFrame({"symbol": [], "side": [], "qty": [], "price": []})


def create_pnl_table():
    return pd.DataFrame(
        {"symbol": ["BTC", "ETH", "LTC"], "qty": [0, 0, 0], "vwap": [0, 0, 0], "upl": [0, 0, 0], "rpl": [0, 0, 0],
         "price": [0, 0, 0]})


def get_currency_price(currency_ticker, client=None):
    if currency_ticker == "CS":
        return 1.0
    if client is None:
        client = cbpro.PublicClient()
    pstr = client.get_product_24hr_stats("{0}-USD".format(currency_ticker))["last"]
    return float(pstr)


class State:
    def __init__(self, initial_money=100000):
        self.current_money = initial_money
        self.symbol_table = create_symbol_table()
        self.trans_table = create_transaction_table()
        self.pnl_table = create_pnl_table()
        self.client = cbpro.PublicClient()
        self.stocks = {}

    def do_transaction(self, symbol, side, qty):
        """
        :param symbol:
        :param side:
        :param qty:
        :return: (0/1, msg), 1 successful, 0 otherwise
        """
        price = get_currency_price(symbol, self.client)
        assert side in ["buy", "sell"], "invalid side={0}".format(side)
        mask = self.pnl_table["symbol"] == symbol
        if side == "buy":
            required_money = qty * price
            if self.current_money < required_money:
                msg = "Insufficient Fund. You have {0}, you need {1}".format(self.current_money, required_money)
                return 0, msg, price
            else:
                # update money
                self.current_money -= required_money
                # update pnl table - average price
                old_price = self.pnl_table[mask]["vwap"]
                old_quantity = self.pnl_table[mask]["qty"]
                self.pnl_table.loc[mask, "vwap"] = ((old_price * old_quantity) + (price * qty)) / (qty + old_quantity)
                # update pnl table - quantity
                self.pnl_table.loc[mask, "qty"] += qty

        elif side == "sell":
            current_qty = self.pnl_table[self.pnl_table["symbol"] == symbol]["qty"].values[0]
            if current_qty < qty:
                msg = "Insufficient stock. You have {0}, you need {1}".format(current_qty, qty)
                return 0, msg, price
            else:
                # update money
                self.current_money += (qty * price)
                # update pnl_table: quantity
                self.pnl_table.loc[mask, "qty"] -= qty
                # update pnl_table: upl
                pervious_price = self.pnl_table.loc[mask]["vwap"]
                self.pnl_table.loc[mask, "rpl"] += ((price - pervious_price) * qty)
                # update pnl_table: if all sold, vwap becomes 0
                if self.pnl_table.loc[mask]["qty"].values[0] == 0:
                    self.pnl_table.loc[mask, "vwap"] = 0
        # modify the transaction table
        self.trans_table = self.trans_table.append({"symbol": symbol, "side": side, "qty": qty, "price": price},
                                                   ignore_index=True)
        # always update upl when doing transaction
        self.update_upl()
        return 1, "", price

    def update_upl(self):
        for symbol in self.symbol_table["symbol"]:
            price = get_currency_price(symbol, self.client)
            mask = self.pnl_table["symbol"] == symbol
            vwap = self.pnl_table[mask]["vwap"]
            qty = self.pnl_table[mask]["qty"]
            self.pnl_table.loc[mask, "upl"] = (price - vwap) * qty
            self.pnl_table.loc[mask, "price"] = price

def is_int(s):
    try:
        int(s)
        return True
    except ValueError:
        return False

current_state = State()
global_obj = []

app = Flask(__name__)
app.secret_key = b'_5#y2L"F4Q8z\n\xec]/'

@app.route('/')
def index():
    btc_price,eth_price,ltc_price = get_prices()
    return render_template('main.html',btc_price=btc_price, eth_price=eth_price, ltc_price=ltc_price)


@app.route('/buy', methods=('GET', 'POST'))
def buy():
    """
    Function that handles the main page
    :return:
    """
    global current_state
    if request.method == 'POST':
        # fetch input
        currency = request.form["currency_select"]
        qty = request.form["Quantity"]
        direction = request.form["direction_select"]
        # check if qty is valid
        if not is_int(qty):
            flash("Please enter a valid positive integer value for Quantity.")
            return render_template('buy.html', current_cash=current_state.current_money)
        qty = int(qty)
        if qty <= 0:
            flash("Please enter a valid positive integer value for Quantity.")
            return render_template('buy.html', current_cash=current_state.current_money)

        # execute user's command
        status, msg, price = current_state.do_transaction(currency, direction.lower(), qty)
        if status == 0:
            flash(msg)
            return render_template('buy.html', current_cash=current_state.current_money)
        else:
            flash("Successfully {0} {1} {2} at price {3}".format(direction, qty, currency, price))
            return render_template('buy.html', current_cash=current_state.current_money)
    else:
        return render_template('buy.html', current_cash=current_state.current_money)


def show_table(data, title):
    """
    Function that convert a table into html
    :param data:
    :return:
    """
    return render_template('table.html', tables=[data.to_html()], title=title, titles=[])



@app.route("/transaction")
def transaction():
    global current_state
    return show_table(current_state.trans_table, title="Transactions")
    

@app.route("/pnl")
def performance():
    global current_state
    current_state.update_upl()
    return show_table(current_state.pnl_table, title="Profit & Loss")