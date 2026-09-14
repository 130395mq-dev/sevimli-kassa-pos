import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from pos.cart import Cart, PaymentPlan
from pos.hub import LiveBackend, HubConnError, HubError
from pos.money import refund_total
from pos.store import Store
from pos.test_store import FakeHub, PRODUCTS as ROWS, METHODS
from shared.receipt import SaleReceipt, render_sale


class ReceiptIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'kassa.db'
        self.store = Store(self.path)
        self.store.replace_products(ROWS)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_discounted_return_uses_original_net_amount(self):
        item = {'origin_item_id': 7, 'product_id': 1, 'ms_product_id': 'ms-1',
                'name': 'Non', 'price': 300000, 'sold_qty': '1',
                'refund_total': 270000, 'returned_qty': 0, 'returned_total': 0}
        backend = LiveBackend(FakeHub(), self.store, METHODS)
        self.assertEqual(backend.submit_return({'id': 1, 'net_total': 270000},
                         [{'item': item, 'qty': 1}], 'naqd'), 270000)
        payload = json.loads(self.store.pending()[0]['payload'])
        self.assertEqual(payload['items'][0]['origin_item_id'], 7)
        self.assertEqual(payload['payments'][0]['amount'], 270000)

    def test_partial_refunds_round_cumulatively(self):
        item = {'sold_qty': '3', 'refund_total': 799900}
        amounts = []
        for n in range(3):
            item['returned_qty'] = n
            item['returned_total'] = sum(amounts)
            amounts.append(refund_total(item, 1))
        self.assertEqual(amounts, [266633, 266634, 266633])

    def test_bonus_only_return_preserves_inventory_without_fake_payment(self):
        item = {'origin_item_id': 7, 'product_id': 1, 'name': 'Non', 'price': 300000,
                'sold_qty': '1', 'refund_total': 0}
        backend = LiveBackend(FakeHub(), self.store, METHODS)
        backend.submit_return({'id': 1, 'net_total': 0}, [{'item': item, 'qty': 1}], 'naqd')
        payload = json.loads(self.store.pending()[0]['payload'])
        self.assertEqual(payload['payments'], [])
        self.assertEqual(payload['items'][0]['quantity'], '1')

    def test_cash_retry_survives_restart_with_same_uuid(self):
        calls = []
        class CashHub:
            def cash(self, **payload):
                calls.append(payload)
                if len(calls) == 1:
                    raise HubConnError('response lost')
                return {'id': 42, 'duplicate': True}
        backend = LiveBackend(CashHub(), self.store, METHODS)
        with self.assertRaises(HubConnError):
            backend.cash('out', 1000000)
        self.store.close()
        self.store = Store(self.path)
        backend = LiveBackend(CashHub(), self.store, METHODS)
        self.assertEqual(backend.cash('out', 1000000)['id'], 42)
        self.assertEqual(calls[0], calls[1])
        self.assertFalse(self.store.get('pending_cash_operation'))

    def test_offline_receipt_becomes_official_after_delivery(self):
        hub = FakeHub(online=False)
        backend = LiveBackend(hub, self.store, METHODS)
        cart = Cart()
        cart.add(self.store.by_barcode(ROWS[0]['barcode']), 1)
        plan = PaymentPlan(cart.total)
        plan.add_cash(cart.total)
        backend.submit(cart, plan)
        payload = json.loads(self.store.pending()[0]['payload'])
        number = backend.last_receipt_number
        self.assertEqual(number, 'MoySklad: kutilmoqda')
        receipt = SaleReceipt(market='Sevimli', point='Test', cashier='Test', shift_no=1,
            number=number, when=datetime.now(), items=[], gross_total=cart.total,
            discount_total=0, net_total=cart.total)
        for width in (32, 48):
            text = render_sale(receipt, width)
            self.assertIn(number, text)
            self.assertTrue(all(len(line) <= width for line in text.splitlines()))
        hub.online = True
        self.assertEqual(backend.flush(), 1)
        saved = json.loads(self.store.recent_sales(1)[0]['payload'])
        self.assertEqual(saved['receipt_number'], 'ОТ-0001')

    def test_pending_local_refund_is_included_in_next_quote(self):
        item = {'origin_item_id': 7, 'product_id': 1, 'ms_product_id': 'ms-1',
                'name': 'Non', 'price': 300000, 'sold_qty': '3',
                'refund_total': 799900, 'returned_qty': 0, 'returned_total': 0}
        class ReturnHub(FakeHub):
            def returnable_sales(self, query='', offset=0):
                return [{'id': 1, 'net_total': 799900, 'items': [dict(item)]}]
        backend = LiveBackend(ReturnHub(), self.store, METHODS)
        backend.submit_return({'id': 1, 'net_total': 799900}, [{'item': item, 'qty': 1}], 'naqd')
        quoted = backend.returnable_sales()[0]['items'][0]
        self.assertEqual(quoted['returned_qty'], '1')
        self.assertEqual(refund_total(quoted, 1), 266634)
