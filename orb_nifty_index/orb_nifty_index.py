# -*- coding: utf-8 -*-
"""
Zerodha Kite Connect - Historical Data

"""
from enum import Enum
import traceback

from utility.quotes_utility import *
from utility.nse_utility import *
from utility.utility import *
from user_interface.adapter.config import *
from user_interface.adapter.trade_day_data import *
from user_interface.adapter.cockpit import *
import datetime      # ✅ module import, use datetime.datetime.today()
from datetime import datetime, timedelta  # ✅ direct import, use datetime.today()
from datatypes.option_straddle_types import *



#Value should be equal 0 on market day
DAY_PRESET = 0
TESTING = 1
#for testing value can be changed, correct value is 1
SLEEP_DIV_FACTOR = 5

# Defines
BUY_STRADDLE_START_INDEX = 0
SELL_STRADDLE_START_INDEX = 2

#status values
class Trade_Status(Enum):
    NOT_TRADED = 0
    ORDER_PLACED = 1
    ORDER_EXECUTED = 2
    EXITED_WITH_TARGET = 3
    EXITED_WITH_SL = 4
    REENTRY_ORDER_PLACES = 5

#exit order type
class Exit_Order_Type(Enum):
    NONE = 0
    TARGET = 1
    STOP_LOSS = 2


class OrbNiftyIndexTradeData:
    def __init__(self, p_option_name, p_option_parent_name, p_option_type, p_trade_type, p_quantity, p_symbol_type , p_week_type="current", market_type="EQ"):
        self.option_name = p_option_name
        self.option_parent_name = p_option_parent_name
        self.option_type = p_option_type
        self.trade_type = p_trade_type
        self.market_type = ""
        self.option_price = ""
        self.status = Trade_Status.NOT_TRADED
        self.exit_order_type = Exit_Order_Type.NONE
        self.entry_order_no = ""
        self.exit_order_no = ""
        self.quantity = p_quantity
        self.market_type = market_type
        self.expiry_day = ""
        self.is_monthly_expiry = False
        self.lst_trading_options = []


#logic class
class LogicORBNiftyIndex:
    def __init__(self, order_utility, \
                 trade_utility, option_chain_utility, quotes_utility, nse_utility, \
                 ui_adapter_config, ui_adapter_trade_day_data, ui_adapter_cockpit):
        # initialization from arguments
        self.logic_name = "LogicORBNiftyIndex"
        self.order_utility = order_utility
        self.trade_utility = trade_utility
        self.option_chain_utility = option_chain_utility
        self.nse_utility = nse_utility
        self.quotes_utility: QuoteUtility = quotes_utility
        self.nifty_future: str = ""

        #config data
        self.ui_adapter_config: UserInterfaceAdapterConfig = ui_adapter_config
        self.config_data = self.ui_adapter_config.get_data()

        self.ui_adapter_trade_day_data: UserInterfaceAdapterTradeDayData = ui_adapter_trade_day_data
        self.test_mode = self.config_data.test_mode_status

        self.ui_adapter_cockpit: UserInterfaceCockpitData = ui_adapter_cockpit

        #pre requisite complete eent
        self.pre_requisite_complete_event = threading.Event()

        #set the quote data object
        self.func_quote_data = self.quotes_utility.get_quote_data
        self.sleep_division_factor = 1 if self.test_mode == False else SLEEP_DIV_FACTOR
        self.day_preset = 0 if not self.test_mode else self.config_data.test_mode_delta_days
        self.amo = "No" if not self.test_mode else "Yes"
        #self.current_week_day = get_week_day_by_date(datetime.today() - timedelta(self.day_preset))

        #update the trade date
        trade_day = date.today() - timedelta(self.day_preset)
        date_str = trade_day.strftime("%d-%m-%Y")
        self.ui_adapter_trade_day_data.update_trade_date(date_str)


        #pre requisite start time
        self.pre_requisite_start_time = (datetime.now() + timedelta(seconds=10)).strftime('%H:%M:%S')

        #start time
        self.execution_start_time = self.config_data.start_time

        #stop time
        self.execution_stop_time = self.config_data.end_time


        #start the thread
        self.pre_requisite_thread = threading.Thread(target=self.pre_requisite_thread_handler)
        self.execute_thread = threading.Thread(target=self.execute)
        self.exit_thread = threading.Thread(target=self.exit_execution_thread)
        self.isFirstTime = True

        self.ohlc_index = 0
        self.volume_index = 0
        self.volume_vix = 0
        self.option_chain_index = 0
        self.prev_ohlc_index = 0

        # start the prerequisite thread
        self.pre_requisite_thread.start()
        # start the thread
        self.execute_thread.start()
        # start the close order thread

        #start exit thread
        self.exit_thread.start()

        #result data
        self.result_data = ResultData()


    def pre_requisite_thread_handler(self):
        print("Prerequsite Thread", self.pre_requisite_start_time, type(self.pre_requisite_start_time))
        self.pre_requisite_complete_event.set()

    def execute(self):
        self.pre_requisite_complete_event.wait()
        self.__prerequisite()
        print("self.config_data.start_time", self.config_data.start_time)
        time_obj = datetime.strptime(self.config_data.start_time, "%H:%M:%S").time()
        start_time = datetime.combine(datetime.today(), time_obj)
        i_sleep_time = (start_time - datetime.now()).seconds
        print("i_sleep_time: ", i_sleep_time)
        time.sleep(i_sleep_time)
        print("Execute Thread - Prerequisite End")
        while True:
            end_time = datetime.strptime(self.config_data.end_time, '%H:%M:%S')
            is_trade_time_expired = is_trade_start_time_expired(end_time)
            if not is_trade_time_expired:
                #get nifty50 candle data
                candle_data_nifty50 = self.__get_candle_data("NIFTY50-INDEX")
                self.__update_ohlc(candle_data_nifty50)

                #get nifty future candle data
                candle_data_niftyfut = self.__get_candle_data(self.nifty_future)
                self.__update_volume(candle_data_niftyfut)

                candle_data_vix = self.__get_candle_data("INDIAVIX-INDEX")
                self.__update_vix(candle_data_vix)

                self.__update_option_chain(candle_data_nifty50)

                if not self.config_data.test_mode_status:
                    time.sleep(15)
                else:
                    time.sleep(0.25)
            else:
                break

    def exit_execution_thread(self):
        print("Start of Exiting Thread")
        end_time = datetime.strptime(self.config_data.end_time, '%H:%M:%S')
        i_sleep_time = (end_time - datetime.now()).seconds
        time.sleep(i_sleep_time)
        print("End of Exiting Thread")

    def get_thread_info(self):
        return self.exit_thread

    # private functions
    def __get_candle_data(self, ticker):
        str_date = datetime.today() - timedelta(days=self.day_preset)
        str_from_date, str_to_date = self.trade_utility.get_broker_utility().getTimeFrame(str_start_time="09:15:00",
                                                                     str_stop_time="15:30:00", date=str_date)

        candle_data = self.trade_utility.get_broker_utility().fetchOHLC(ticker=ticker,\
                                                    str_from_date=str_from_date,\
                                                    str_to_date=str_to_date,\
                                                    interval="1minute",\
                                                    all_data=False,\
                                                    exchange="NSE",\
                                                    market_type="NFO")
        if len(candle_data) > 0:
            if "09:14:00" in candle_data[DATE_TIME][0]:
                candle_data = candle_data.drop(candle_data.index[0]).reset_index(drop=True)
        return candle_data

    def __get_prev_day_candle_data(self, ticker):
        prev_trade_day = self.nse_utility.get_prev_day_trade_date(self.day_preset)
        str_date = datetime.strptime(prev_trade_day, "%Y-%m-%d")
        print("str_date: ", str_date, type(str_date))
        str_from_date, str_to_date = self.option_chain_utility.get_broker_utility().getTimeFrame(str_start_time="09:15:00",
                                                                     str_stop_time="15:30:00", start_date=str_date, stop_date=str_date)

        candle_data = self.option_chain_utility.get_broker_utility().fetchOHLC(ticker=ticker,\
                                                    str_from_date=str_from_date,\
                                                    str_to_date=str_to_date,\
                                                    interval="1Day",\
                                                    all_data=False,\
                                                    exchange="NSE",\
                                                    market_type="")
        return candle_data

    def __get_prev_week_candle_data(self, ticker):
        #pass 1 for tuesday
        prev_prev_week_day, prev_week_day = get_previous_expirty_day(1, self.day_preset)
        str_date = datetime.strptime(prev_prev_week_day, "%Y-%m-%d")
        end_date = datetime.strptime(prev_week_day, "%Y-%m-%d")
        print("str_date: ", str_date, type(str_date))
        str_from_date, str_to_date = self.option_chain_utility.get_broker_utility().getTimeFrame(
            str_start_time="09:15:00",
            str_stop_time="15:30:00", start_date=str_date, stop_date=end_date)

        candle_data = self.option_chain_utility.get_broker_utility().fetchOHLC(ticker=ticker,\
                                                    str_from_date=str_from_date,\
                                                    str_to_date=str_to_date,\
                                                    interval="1Day",\
                                                    all_data=False,\
                                                    exchange="NSE",\
                                                    market_type="")
        return candle_data


    def __get_option_chain(self, ticker):
        return self.option_chain_utility.get_broker_utility().getOptionChain(ticker)

    def __update_ohlc(self, candle_data):
        if self.ohlc_index < len(candle_data):
            try:
                #print(self.ohlc_index)
                self.ui_adapter_trade_day_data.update_ohlc(self.ohlc_index + 2, \
                                                             candle_data[OPEN_PRICE][self.ohlc_index], candle_data[HIGH_PRICE][self.ohlc_index], \
                                                           candle_data[LOW_PRICE][self.ohlc_index], candle_data[CLOSE_PRICE][self.ohlc_index])
                self.ohlc_index = self.ohlc_index + 1
            except:
                print("Exception while updating ohlc: ", self.ohlc_index, len(candle_data))

    def __update_volume(self, candle_data):
        #print("len(candle_data_2): ", len(candle_data))
        if self.volume_index < len(candle_data):
            try:
                #print(self.volume_index)
                self.ui_adapter_trade_day_data.update_volume(self.volume_index + 2, candle_data[VOLUME_DATA][self.volume_index])
                self.volume_index = self.volume_index + 1
            except:
                print("Exception while updating volume: ", self.volume_index, len(candle_data))

    def __update_vix(self, candle_data):
        #print("len(candle_data_2): ", len(candle_data))
        if self.volume_vix < len(candle_data):
            try:
                #print(self.volume_index)
                self.ui_adapter_trade_day_data.update_vix(self.volume_vix + 2, candle_data[CLOSE_PRICE][self.volume_vix])
                self.volume_vix = self.volume_vix + 1
            except:
                print("Exception while updating vix: ", self.volume_vix, len(candle_data))

    def __update_option_chain(self, candle_data):
        if len(candle_data) > 0:
            if self.ohlc_index % 15 == 1 or self.ohlc_index == 6 or self.ohlc_index == 366:
                print("self.ohlc_index: ", self.ohlc_index, candle_data[DATE_TIME][self.ohlc_index - 1])
                try:
                    if not self.ohlc_index == self.prev_ohlc_index:
                        self.prev_ohlc_index = self.ohlc_index
                        l_index = self.ohlc_index - 1
                        option_chain, total_call_oi, total_put_oi = self.__get_option_chain("NIFTY50-INDEX")
                        option_chain_data = get_option_chain_data(candle_data[DATE_TIME][l_index], \
                                                                  candle_data[CLOSE_PRICE][l_index], 50, \
                                                                  option_chain, total_call_oi, total_put_oi)
                        self.ui_adapter_trade_day_data.update_option_chain(self.option_chain_index + 2, option_chain_data)
                        self.option_chain_index = self.option_chain_index + 1
                except:
                    traceback.print_exc()
                    print("Exception while updating option chain data: ", self.option_chain_index, len(candle_data))


    def __add_options_data(self):
        l_quantity = int(self.ui_data.quantity) * self.nse_utility.get_fno_lot_size(self.ui_data.index)
        lst_split_expiry_date = self.ui_data.expiry_buy.split("-")
        option_name = self.ui_data.index + lst_split_expiry_date[0] + lst_split_expiry_date[1].upper() + \
                      lst_split_expiry_date[2][2:] + str(self.atm) + "PE"
        globals()[f"obj_trade_data_{option_name}_buy_pe"] = OptionStraddleData(p_option_name=option_name,\
                                                                           p_option_parent_name=self.ui_data.index,\
                                                                           p_option_type="PE",
                                                                           p_trade_type=DEFINE_TRADE_TYPE_BUY,
                                                                           p_quantity=l_quantity,
                                                                           p_symbol_type=SYMBOL_TYPE_OPTION,
                                                                           market_type="")
        self.lst_trading_options.append(globals()[f"obj_trade_data_{option_name}_buy_pe"])
        self.quotes_utility.add_stocks([option_name], [""])

        option_name = self.ui_data.index + lst_split_expiry_date[0] + lst_split_expiry_date[1].upper() + \
                      lst_split_expiry_date[2][2:] + str(self.atm) + "CE"
        globals()[f"obj_trade_data_{option_name}_buy_ce"] = OptionStraddleData(p_option_name=option_name, p_option_parent_name=self.ui_data.index,\
                                                                           p_option_type="CE",
                                                                           p_trade_type=DEFINE_TRADE_TYPE_BUY,
                                                                           p_quantity=l_quantity,
                                                                           p_symbol_type=SYMBOL_TYPE_OPTION,
                                                                           market_type="")
        self.lst_trading_options.append(globals()[f"obj_trade_data_{option_name}_buy_ce"])
        self.quotes_utility.add_stocks([option_name], [""])

        lst_split_expiry_date = self.ui_data.expiry_sell.split("-")
        option_name = self.ui_data.index + lst_split_expiry_date[0] + lst_split_expiry_date[1].upper() + \
                      lst_split_expiry_date[2][2:] + str(self.atm) + "PE"
        globals()[f"obj_trade_data_{option_name}_sell_pe"] = OptionStraddleData(p_option_name=option_name, p_option_parent_name=self.ui_data.index,
                                                                         p_option_type="PE",
                                                                         p_trade_type=DEFINE_TRADE_TYPE_SELL,
                                                                         p_quantity=l_quantity,
                                                                         p_symbol_type=SYMBOL_TYPE_OPTION,
                                                                         market_type="")
        self.lst_trading_options.append(globals()[f"obj_trade_data_{option_name}_sell_pe"])
        self.quotes_utility.add_stocks([option_name], [""])

        option_name = self.ui_data.index + lst_split_expiry_date[0] + lst_split_expiry_date[1].upper() + \
                      lst_split_expiry_date[2][2:] + str(self.atm) + "PE"
        globals()[f"obj_trade_data_{option_name}_sell_ce"] = OptionStraddleData(p_option_name=option_name, p_option_parent_name=self.ui_data.index,
                                                                         p_option_type="CE",
                                                                         p_trade_type=DEFINE_TRADE_TYPE_SELL,
                                                                         p_quantity=l_quantity,
                                                                         p_symbol_type=SYMBOL_TYPE_OPTION,
                                                                         market_type="")
        self.lst_trading_options.append(globals()[f"obj_trade_data_{option_name}_sell_ce"])
        self.quotes_utility.add_stocks([option_name], [""])
        for data in self.lst_trading_options:
            print("option list: ", data.option_name)

    def __prerequisite(self):
        print("Execute Thread - Prerequisite Start")
        expiry_date = self.nse_utility.get_index_expiry_date("NIFTY", self.config_data.test_mode_delta_days)
        print("expirty data: ", expiry_date)
        self.nifty_future = self.trade_utility.get_broker_utility().get_future_name("NIFTY", expiry_date[2])
        print("self.nifty_future: ", self.nifty_future)

        #previous day candle data
        nifty50_prev_day_candle_data = self.__get_prev_day_candle_data("NIFTY50-INDEX")
        if len(nifty50_prev_day_candle_data) > 0:
            #print("prev_day_candle_data: ", nifty50_prev_day_candle_data[HIGH_PRICE][0], nifty50_prev_day_candle_data[LOW_PRICE][0], nifty50_prev_day_candle_data[CLOSE_PRICE][0])
            self.ui_adapter_cockpit.update_prev_day_ohlc(nifty50_prev_day_candle_data[HIGH_PRICE][0], \
                                                         nifty50_prev_day_candle_data[LOW_PRICE][0], \
                                                         nifty50_prev_day_candle_data[CLOSE_PRICE][0])

        nifty50_prev_week_candle_data = self.__get_prev_week_candle_data("NIFTY50-INDEX")
        if len(nifty50_prev_week_candle_data) > 0:
            #print("prev_day_candle_data: ", nifty50_prev_week_candle_data[HIGH_PRICE].max(),
            #      nifty50_prev_week_candle_data[LOW_PRICE].min())
            self.ui_adapter_cockpit.update_prev_week_data(nifty50_prev_week_candle_data[HIGH_PRICE].max(), \
                                                          nifty50_prev_week_candle_data[LOW_PRICE].min())


    def __get_atm(self):
        self.quotes_utility.add_stocks([self.ui_data.index], [""])
        dict_quote_data = self.quotes_utility.get_quote_data()
        self.quotes_utility.remove_stock(self.ui_data.index)
        if self.ui_data.index in dict_quote_data:
            self.atm = round(dict_quote_data[self.ui_data.index].ltp /50) * 50
            self.ui_adapter.update_atm(self.atm)


    def __handle_trade_check(self):
        #print("handle trade check")
        self.__handle_trade_check_buy()
        self.__handle_trade_check_sell()


    def __handle_trade_check_buy(self):
        print("handle trade check buy")
        total_straddle_price = 0
        for data in self.lst_trading_options[:2]:
            total_straddle_price += self.dictQuoteData[data.option_name].ltp

        if self.buy_straddle_status == Trade_Status.NOT_TRADED:
            print("Placing Order of buy straddle")
        elif self.buy_straddle_status == Trade_Status.ORDER_EXECUTED:
            target_value = float(self.ui_data.buy_total_price) + (float(self.ui_data.buy_total_price) * (float(self.ui_data.target_percentage) / 100))
            stop_loss_value = float(self.ui_data.buy_total_price) - (float(self.ui_data.buy_total_price) * (
                        float(self.ui_data.stop_loss_percentage) / 100))
            if target_value >= total_straddle_price or total_straddle_price <= stop_loss_value:
                self.__execute_exit(BUY_STRADDLE_START_INDEX)
                self.buy_straddle_status = Trade_Status.EXITED_WITH_TARGET

    def __handle_trade_check_sell(self):
        #print("handle trade check sell")
        total_straddle_price = 0
        for data in self.lst_trading_options[-2:]:
            total_straddle_price += self.dictQuoteData[data.option_name].ltp

        if self.sell_straddle_status == Trade_Status.NOT_TRADED:
            if total_straddle_price > float(self.ui_data.buy_total_price):
                print("Placing Order of sell straddle")
                self.__execute_entry(SELL_STRADDLE_START_INDEX)
                self.sell_straddle_status = Trade_Status.ORDER_EXECUTED
        elif self.sell_straddle_status == Trade_Status.ORDER_EXECUTED:
            target_value = float(self.ui_data.buy_total_price) + (
                        float(self.ui_data.buy_total_price) * (float(self.ui_data.target_percentage) / 100))
            stop_loss_value = float(self.ui_data.buy_total_price) - (float(self.ui_data.buy_total_price) * (
                    float(self.ui_data.stop_loss_percentage) / 100))
            if target_value <= total_straddle_price or total_straddle_price >= stop_loss_value:
                self.__execute_exit(SELL_STRADDLE_START_INDEX)
                self.sell_straddle_status = Trade_Status.EXITED_WITH_TARGET

    def __execute_entry(self, start_index):
        print("Inside __execute_entry")
        self.__place_entry_order(self.lst_trading_options[start_index])
        if not self.lst_trading_options[start_index].entry_order_no == "":
            self.__place_entry_order(self.lst_trading_options[start_index + 1])
            if self.lst_trading_options[0].entry_order_no == "":
                print("Second buy order failed", self.lst_trading_options[start_index + 1].option_type)
        else:
            print("First buy order failed", self.lst_trading_options[start_index].option_type)

    def __execute_exit(self, start_index):
        print("Inside __execute_exit")
        if not self.lst_trading_options[start_index].entry_order_no == "":
            self.__place_exit_order(self.lst_trading_options[start_index])
            if not self.lst_trading_options[start_index].exit_order_no == "":
                print("Exit Order Failed", self.lst_trading_options[start_index].trade_type,
                      self.lst_trading_options[start_index].option_type)

        self.__place_exit_order(self.lst_trading_options[start_index + 1])
        if not self.lst_trading_options[start_index + 1].entry_order_no == "":
            if not self.lst_trading_options[start_index + 1].exit_order_no == "":
                print("Exit Order Failed", self.lst_trading_options[1].trade_type,
                      self.lst_trading_options[start_index + 1].option_type)

    def __place_entry_order(self, p_obj_trade_data:OrbNiftyIndexTradeData):
        print("Place Entry Order", p_obj_trade_data.option_name, p_obj_trade_data.trade_type, p_obj_trade_data.market_type)
        p_obj_trade_data.entry_order_no = (
            self.order_utility.get_broker_utility().place_order(tradingsymbol=p_obj_trade_data.option_name,\
                transaction_type=p_obj_trade_data.trade_type,\
                quantity=p_obj_trade_data.quantity,\
                order_type="MARKET",\
                market_type=p_obj_trade_data.market_type,\
                amo=self.amo\
            )
        )

        if not p_obj_trade_data.entry_order_no == "":
            p_obj_trade_data.status = Trade_Status.ORDER_PLACED

    def __place_exit_order(self, p_obj_trade_data:OrbNiftyIndexTradeData):
        print("Place Exit Order: ", p_obj_trade_data.option_name, p_obj_trade_data.trade_type)
        l_str_trade_type = DEFINE_TRADE_TYPE_SELL if p_obj_trade_data.trade_type == DEFINE_TRADE_TYPE_BUY else DEFINE_TRADE_TYPE_BUY

        p_obj_trade_data.exit_order_no = self.order_utility.get_broker_utility().place_order(
                                                         tradingsymbol=p_obj_trade_data.option_name,
                                                        transaction_type=l_str_trade_type,
                                                        quantity=p_obj_trade_data.quantity,
                                                        order_type="MARKET",
                                                        price=0,
                                                        market_type=p_obj_trade_data.market_type,
                                                        amo=self.amo)
        if not p_obj_trade_data.entry_order_no == "":
            p_obj_trade_data.exit_order_type = Exit_Order_Type.TARGET

    def __modify_order_to_sl(self, p_obj_trade_data:OrbNiftyIndexTradeData):
        print("Modify order to stoploss: ", p_obj_trade_data.option_name,
              p_obj_trade_data.trade_type)
        p_obj_trade_data.exit_order_no = self.order_utility.get_broker_utility().modify_order(order_id=p_obj_trade_data.exit_order_no,
                                                                             quantity=p_obj_trade_data.quantity,
                                                                             market_type=p_obj_trade_data.market_type,
                                                                             order_type="MARKET")
    def __cancel_order(self, p_order_no):
        print("Cancel order to target: ", p_order_no)
        self.order_utility.get_broker_utility().cancel_order(p_order_no)

    def __update_result_data(self):
        print("Updating resulte data")
        lst_result_data = []


