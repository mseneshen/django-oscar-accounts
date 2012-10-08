from decimal import Decimal as D
import json
import base64

from django import test
from django.test.client import Client
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse

from accounts import models

USERNAME, PASSWORD = 'client', 'password'


def get_headers():
    # Create a user to authenticate as
    try:
        User.objects.get(username=USERNAME)
    except User.DoesNotExist:
        User.objects.create_user(USERNAME, None, PASSWORD)
    auth = "%s:%s" % (USERNAME, PASSWORD)
    auth_headers = {
        'HTTP_AUTHORIZATION': 'Basic %s' % base64.b64encode(auth)
    }
    return auth_headers


def get(url):
    return Client().get(url, **get_headers())


def post(url, payload):
    """
    POST a JSON-encoded payload
    """
    return Client().post(
        url, json.dumps(payload),
        content_type="application/json",
        **get_headers())


class TestCreatingAnAccountErrors(test.TestCase):

    def setUp(self):
        self.payload = {
            'start_date': '2013-01-01T09:00:00+03:00',
            'end_date': '2013-06-01T09:00:00+03:00',
            'amount': '400.00',
        }

    def test_missing_dates(self):
        payload = self.payload.copy()
        del payload['start_date']
        response = post(reverse('accounts'), payload)
        self.assertEqual(400, response.status_code)
        self.assertTrue('message' in json.loads(response.content))

    def test_timezone_naive_start_date(self):
        payload = self.payload.copy()
        payload['start_date'] = '2013-01-01T09:00:00'
        response = post(reverse('accounts'), payload)
        self.assertEqual(400, response.status_code)
        self.assertTrue('message' in json.loads(response.content))

    def test_timezone_naive_end_date(self):
        payload = self.payload.copy()
        payload['end_date'] = '2013-06-01T09:00:00'
        response = post(reverse('accounts'), payload)
        self.assertEqual(400, response.status_code)
        self.assertTrue('message' in json.loads(response.content))

    def test_dates_in_wrong_order(self):
        payload = self.payload.copy()
        payload['start_date'] = '2013-06-01T09:00:00+03:00'
        payload['end_date'] = '2013-01-01T09:00:00+03:00'
        response = post(reverse('accounts'), payload)
        self.assertEqual(400, response.status_code)
        self.assertTrue('message' in json.loads(response.content))

    def test_invalid_amount(self):
        payload = self.payload.copy()
        payload['amount'] = 'silly'
        response = post(reverse('accounts'), payload)
        self.assertEqual(400, response.status_code)
        self.assertTrue('message' in json.loads(response.content))

    def test_negative_amount(self):
        payload = self.payload.copy()
        payload['amount'] = '-100'
        response = post(reverse('accounts'), payload)
        self.assertEqual(400, response.status_code)
        self.assertTrue('message' in json.loads(response.content))

    def test_amount_too_low(self):
        payload = self.payload.copy()
        payload['amount'] = '1.00'
        with self.settings(ACCOUNTS_MIN_LOAD_VALUE=D('25.00')):
            response = post(reverse('accounts'), payload)
        self.assertEqual(403, response.status_code)
        data = json.loads(response.content)
        self.assertEqual('C101', data['code'])

    def test_amount_too_high(self):
        payload = self.payload.copy()
        payload['amount'] = '5000.00'
        with self.settings(ACCOUNTS_MAX_ACCOUNT_VALUE=D('500.00')):
            response = post(reverse('accounts'), payload)
        self.assertEqual(403, response.status_code)
        data = json.loads(response.content)
        self.assertEqual('C102', data['code'])


class TestSuccessfullyCreatingAnAccount(test.TestCase):

    def setUp(self):
        self.payload = {
            'start_date': '2013-01-01T09:00:00+03:00',
            'end_date': '2013-06-01T09:00:00+03:00',
            'amount': '400.00',
        }
        # Submit request to create a new account, then fetch the detail
        # page that is returned.
        self.create_response = post(reverse('accounts'), self.payload)
        if 'Location' in self.create_response:
            self.detail_response = get(
                self.create_response['Location'])
            self.payload = json.loads(self.detail_response.content)
            self.account = models.Account.objects.get(
                code=self.payload['code'])

    def test_returns_201(self):
        self.assertEqual(201, self.create_response.status_code)

    def test_returns_a_valid_location(self):
        self.assertEqual(200, self.detail_response.status_code)

    def test_detail_view_returns_correct_keys(self):
        keys = ['code', 'start_date', 'end_date', 'balance']
        for key in keys:
            self.assertTrue(key in self.payload)

    def test_returns_dates_in_utc(self):
        self.assertEqual('2013-01-01T06:00:00+00:00',
                         self.payload['start_date'])
        self.assertEqual('2013-06-01T06:00:00+00:00',
                         self.payload['end_date'])

    def test_loads_the_account_with_the_right_amount(self):
        self.assertEqual('400.00', self.payload['balance'])

    def test_detail_view_returns_redemptions_url(self):
        self.assertTrue('redemptions_url' in self.payload)

    def test_detail_view_returns_refunds_url(self):
        self.assertTrue('refunds_url' in self.payload)


class TestMakingARedemption(test.TestCase):

    def setUp(self):
        self.create_payload = {
            'start_date': '2013-01-01T09:00:00+03:00',
            'end_date': '2013-06-01T09:00:00+03:00',
            'amount': '400.00',
        }
        self.create_response = post(reverse('accounts'), self.create_payload)
        self.detail_response = get(self.create_response['Location'])
        redemption_url = json.loads(self.detail_response.content)['redemptions_url']

        self.redeem_payload = {
            'amount': '50.00',
            'order_number': '1234'
        }
        self.redeem_response = post(redemption_url, self.redeem_payload)

        transfer_url = self.redeem_response['Location']
        self.transfer_response = get(
            transfer_url)

    def test_returns_201_for_the_redeem_request(self):
        self.assertEqual(201, self.redeem_response.status_code)

    def test_returns_valid_transfer_url(self):
        url = self.redeem_response['Location']
        response = get(url)
        self.assertEqual(200, response.status_code)

    def test_returns_the_correct_data_in_the_transfer_request(self):
        data = json.loads(self.transfer_response.content)
        keys = ['source_code', 'source_name', 'destination_code',
                'destination_name', 'amount', 'datetime', 'order_number',
                'description']
        for key in keys:
            self.assertTrue(key in data, "Key '%s' not found in payload" % key)

        self.assertEqual('50.00', data['amount'])
        self.assertIsNone(data['destination_code'])


class TestTransferView(test.TestCase):

    def test_returns_404_for_missing_transfer(self):
        url = reverse('transfer', kwargs={'pk': 11111111})
        response = get(url)
        self.assertEqual(404, response.status_code)


class TestMakingARedemptionThenRefund(test.TestCase):

    def setUp(self):
        self.create_payload = {
            'start_date': '2013-01-01T09:00:00+03:00',
            'end_date': '2013-06-01T09:00:00+03:00',
            'amount': '400.00',
        }
        self.create_response = post(
            reverse('accounts'), self.create_payload)
        self.detail_response = get(self.create_response['Location'])

        self.redeem_payload = {
            'amount': '50.00',
            'order_number': '1234'
        }
        account_dict = json.loads(self.detail_response.content)
        redemption_url = account_dict['redemptions_url']
        self.redeem_response = post(redemption_url, self.redeem_payload)

        self.refund_payload = {
            'amount': '25.00',
            'order_number': '1234',
        }
        refund_url = account_dict['refunds_url']
        self.refund_response = post(refund_url, self.refund_payload)

    def test_returns_201_for_the_refund_request(self):
        self.assertEqual(201, self.refund_response.status_code)


class TestMakingARedemptionThenReverse(test.TestCase):

    def setUp(self):
        self.create_payload = {
            'start_date': '2013-01-01T09:00:00+03:00',
            'end_date': '2013-06-01T09:00:00+03:00',
            'amount': '400.00',
        }
        self.create_response = post(reverse('accounts'), self.create_payload)
        self.detail_response = get(self.create_response['Location'])
        account_dict = json.loads(self.detail_response.content)
        self.redeem_payload = {
            'amount': '50.00',
            'order_number': '1234'
        }
        redemption_url = account_dict['redemptions_url']
        self.redeem_response = post(redemption_url, self.redeem_payload)

        transfer_response = get(self.redeem_response['Location'])
        transfer_dict = json.loads(transfer_response.content)
        self.reverse_payload = {
            'order_number': '1234',
        }
        reverse_url = transfer_dict['reverse_url']
        self.reverse_response = post(reverse_url, self.reverse_payload)

    def test_returns_201_for_the_reverse_request(self):
        self.assertEqual(201, self.reverse_response.status_code)
