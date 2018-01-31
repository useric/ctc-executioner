from trade import Trade
from order import Order
from order_type import OrderType
from order_side import OrderSide
import copy
import logging
import numpy as np

class MatchEngine(object):

    def __init__(self, orderbook, index=0):
        self.orderbook = orderbook
        self.index = index

    def setIndex(self, index):
        self.index = index

    def matchLimitOrder(self, order, orderbookState):
        if order.getSide() == OrderSide.BUY:
            bookSide = orderbookState.getSellers()
        else:
            bookSide = orderbookState.getBuyers()

        def isMatchingPosition(p):
            if order.getSide() == OrderSide.BUY:
                return bookSide[sidePosition].getPrice() <= order.getPrice()
            else:
                return bookSide[sidePosition].getPrice() >= order.getPrice()

        partialTrades = []
        remaining = order.getCty()
        sidePosition = 0
        while len(bookSide) > sidePosition and isMatchingPosition(sidePosition) and remaining > 0.0:
            p = bookSide[sidePosition]
            price = p.getPrice()
            qty = p.getQty()
            if not partialTrades and qty >= order.getCty():
                logging.debug("Full execution: " + str(qty) + " pcs available")
                return [Trade(orderSide=order.getSide(), orderType=OrderType.LIMIT, cty=remaining, price=price)]
            else:
                logging.debug("Partial execution: " + str(qty) + " pcs available")
                partialTrades.append(Trade(orderSide=order.getSide(), orderType=OrderType.LIMIT, cty=min(qty, remaining), price=price))
                sidePosition = sidePosition + 1
                remaining = remaining - qty

                if sidePosition == len(bookSide) - 1:
                    # At this point there is no more liquidity in this state of the order
                    # book (data) but the order price might actually be still higher than
                    # what was available. For convenience sake we assume that there would
                    # be liquidity in the subsequent levels above.
                    # Therefore we linearly interpolate and place fake orders from
                    # imaginary traders in the book with an increased price (according to
                    # derivative) and similar qty.
                    average_qty = np.mean([x.getCty() for x in partialTrades])
                    logging.debug("On average executed qty: " + str(average_qty))
                    if average_qty == 0.0:
                        average_qty = 0.5
                        logging.debug("Since no trades were executed (e.g. true average executed qty == 0.0), defaul is choosen: " + str(average_qty))
                    derivative_price = abs(np.mean(np.gradient([x.getPrice() for x in partialTrades])))
                    logging.debug("Derivative of price from executed trades: " + str(derivative_price))
                    if derivative_price == 0.0:
                        derivative_price = 10.0
                        logging.debug("Since no trades were executed (e.g. derivative executed price == 0.0), defaul is choosen: " + str(derivative_price))
                    while remaining > 0.0:
                        if order.getSide() == OrderSide.BUY:
                            price = price + derivative_price
                            if price > order.getPrice():
                                break
                        elif order.getSide() == OrderSide.SELL:
                            price = price - derivative_price
                            if price < order.getPrice():
                                break

                        qty = min(average_qty, remaining)
                        logging.debug("Partial execution: assume " + str(qty) + " available")
                        partialTrades.append(Trade(orderSide=order.getSide(), orderType=OrderType.LIMIT, cty=qty, price=price))
                        remaining = remaining - qty

        return partialTrades

    def matchMarketOrder(self, order, orderbookState):
        if order.getSide() == OrderSide.BUY:
            bookSide = orderbookState.getSellers()
        else:
            bookSide = orderbookState.getBuyers()

        partialTrades = []
        remaining = order.getCty()
        sidePosition = 0
        price = 0.0
        while len(bookSide) > sidePosition and remaining > 0.0:
            p = bookSide[sidePosition]
            derivative_price = p.getPrice() - price
            price = p.getPrice()
            qty = p.getQty()
            if not partialTrades and qty >= order.getCty():
                logging.debug("Full execution: " + str(qty) + " pcs available")
                return [Trade(orderSide=order.getSide(), orderType=OrderType.MARKET, cty=remaining, price=price)]
            else:
                logging.debug("Partial execution: " + str(qty) + " pcs available")
                partialTrades.append(Trade(orderSide=order.getSide(), orderType=OrderType.MARKET, cty=min(qty, remaining), price=price))
                sidePosition = sidePosition + 1
                remaining = remaining - qty

        # Since there is no more liquidity in this state of the order book
        # (data). For convenience sake we assume that there would be
        # liquidity in some levels below.
        # TODO: Simulate in more appropriate way, such as executing multiple
        # trades whereas the trade size increases exponentially and the price
        # increases logarithmically.
        average_qty = np.mean([x.getCty() for x in partialTrades])
        logging.debug("On average executed qty: " + str(average_qty))
        if average_qty == 0.0:
            average_qty = 0.5
            logging.debug("Since no trades were executed (e.g. true average executed qty == 0.0), defaul is choosen: " + str(average_qty))
        derivative_price = abs(np.mean(np.gradient([x.getPrice() for x in partialTrades])))
        logging.debug("Derivative of price from executed trades: " + str(derivative_price))
        if derivative_price == 0.0:
            derivative_price = 5.0
            logging.debug("Since no trades were executed (e.g. derivative executed price == 0.0), defaul is choosen: " + str(derivative_price))
        while remaining > 0.0:
            if order.getSide() == OrderSide.BUY:
                price = price + derivative_price
            else:
                price = price - derivative_price

            qty = min(average_qty, remaining)
            logging.debug("Partial execution: assume " + str(qty) + " available")
            partialTrades.append(Trade(orderSide=order.getSide(), orderType=OrderType.MARKET, cty=qty, price=price))
            remaining = remaining - qty

        return partialTrades

    def matchOrder(self, order, seconds=None):
        order = copy.deepcopy(order)  # Do not modify original order!
        i = self.index
        remaining = order.getCty()
        trades = []

        while len(self.orderbook.getStates()) > i and remaining > 0:
            orderbookState = self.orderbook.getState(i)
            logging.debug("Evaluate state " + str(i) + ":\n" + str(orderbookState))

            # Stop matching process after defined seconds are consumed
            if seconds is not None:
                t_start = self.orderbook.getState(self.index).getTimestamp()
                t_now = orderbookState.getTimestamp()
                t_delta = (t_now - t_start).total_seconds()
                logging.debug(str(t_delta) + " of " + str(seconds) + " consumed.")
                if t_delta >= seconds:
                    logging.debug("Time delta consumed, stop matching.\n")
                    break

            if order.getType() == OrderType.LIMIT:
                counterTrades = self.matchLimitOrder(order, orderbookState)
            elif order.getType() == OrderType.MARKET:
                counterTrades = self.matchMarketOrder(order, orderbookState)
            elif order.getType() == OrderType.LIMIT_T_MARKET:
                if seconds is None:
                    raise Exception(str(OrderType.LIMIT_T_MARKET) + ' requires a time limit.')
                counterTrades = self.matchLimitOrder(order, orderbookState)
            else:
                raise Exception('Order type not known or not implemented yet.')

            if counterTrades:
                trades = trades + counterTrades
                logging.debug("Trades executed:")
                for counterTrade in counterTrades:
                    logging.debug(counterTrade)
                    remaining = remaining - counterTrade.getCty()
                order.setCty(remaining)
                logging.debug("Remaining: " + str(remaining) + "\n")
            else:
                logging.debug("No orders matched.\n")
            i = i + 1

        # Execute remaining qty as market if LIMIT_T_MARKET
        if remaining > 0.0 and (order.getType() == OrderType.LIMIT_T_MARKET or order.getType() == OrderType.MARKET):
            logging.debug('Execute remaining as MARKET order.')
            i = i - 1  # back to previous state
            if not len(self.orderbook.getStates()) > i:
                raise Exception('Not enough data for following market order.')

            orderbookState = self.orderbook.getState(i)
            logging.debug("Evaluate state " + str(i) + ":\n" + str(orderbookState))
            counterTrades = self.matchMarketOrder(order, orderbookState)
            if not counterTrades:
                raise Exception('Remaining market order matching failed.')
            trades = trades + counterTrades
            logging.debug("Trades executed:")
            for counterTrade in counterTrades:
                logging.debug(counterTrade)
                remaining = remaining - counterTrade.getCty()
            order.setCty(remaining)
            logging.debug("Remaining: " + str(remaining) + "\n")

        logging.debug("Total number of trades: " + str(len(trades)))
        logging.debug("Remaining qty of order: " + str(remaining))
        logging.debug("Index at end of match period: " + str(i))
        return trades, remaining, i-1


# logging.basicConfig(level=logging.DEBUG)
# from orderbook import Orderbook
# orderbook = Orderbook(extraFeatures=False)
# orderbook.loadFromFile('query_result_small.tsv')
# engine = MatchEngine(orderbook, index=0)
#
# #order = Order(orderType=OrderType.LIMIT, orderSide=OrderSide.BUY, cty=11.0, price=16559.0)
# #order = Order(orderType=OrderType.MARKET, orderSide=OrderSide.BUY, cty=25.5, price=None)
# order = Order(orderType=OrderType.LIMIT_T_MARKET, orderSide=OrderSide.SELL, cty=1.0, price=16559.0)
# trades, remaining, i = engine.matchOrder(order, seconds=1.0)
# c = 0.0
# for trade in trades:
#     c = c + trade.getCty()
# print(c)
