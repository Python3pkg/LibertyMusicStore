import string
from decimal import Decimal
from collections import OrderedDict
import logging
from uuid import uuid4
import random
import datetime
import json
import os

import six

from django.db import models
from django.utils.deconstruct import deconstructible
from django.utils.encoding import smart_str
from django.contrib.auth import hashers
from django.core.urlresolvers import reverse
from django.core.cache import get_cache
from django.db.models import Sum
from django.utils import timezone
from django.conf import settings
from django.core.exceptions import ValidationError
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.contrib.contenttypes.generic import GenericForeignKey
from django.contrib.contenttypes.generic import GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core import validators

from jsonfield import JSONField
from easy_thumbnails.fields import ThumbnailerImageField
from autoslug import AutoSlugField

_rate_converter = None

from . import btcaverage


GENRES = (
    (1,  'Rock'),
    (2,  'Metal'),
    (3,  'Alternative'),
    (4,  'Indie'),
    (5,  'Electro'),
    (6,  'Pop'),
    (7,  'R&B'),
    (8,  'Hip Hop/Rap'),
    (9,  'Country/Folk'),
    (17, 'Gospel'),
    (10, 'Blues/Jazz'),
    (11, 'World'),
    (12, 'Reggae'),
    (14, 'Indian music'),
    (15, 'Afro fusion'),
    (16, 'Cont.African'),
    (13, 'Punk'),
    (14, 'Soundtrack'),
)

GENRES_DICT = dict(GENRES)

logger = logging.getLogger("__name__")


def get_rate_converter():
    global _rate_converter
    if not _rate_converter:
        redis = get_cache("default").client.get_client(write=True)
        _rate_converter = btcaverage.RedisConverter(redis)
    return _rate_converter


@deconstructible
class filename_gen(object):
    """Courtesy of http://stackoverflow.com/questions/25767787/django-cannot-create-migrations-for-imagefield-with-dynamic-upload-to-value"""
    def __init__(self, sub_path):
        self.path = sub_path

    def __call__(self, instance, filename):
        salt = hashers.get_hasher().salt()
        salt = smart_str(salt)
        return os.path.join(self.path, salt + "-" + filename)


def update_initial_groups():
    """ Django admin controls the store owner access by using Django auth groups.

    This ensures we have the group set with the correct permissions.
    Run after the syncdb is complete.
    """

    allowed_permissions = ["change_album", "add_album", "change_song", "add_song", "change_store", "change_downloadtransaction"]
    allowed_permissions = Permission.objects.filter(codename__in=allowed_permissions)
    store_operators, created = Group.objects.get_or_create(name="Store operators")
    store_operators.permissions = allowed_permissions
    store_operators.save()


def validate_currency(value):
    currencies = [cur for cur, name in settings.CURRENCIES]
    if value not in currencies:
        raise ValidationError("Only the following currencies are supported: {}".format(", ".join(currencies)))


class UserManager(DjangoUserManager):
    pass


class User(AbstractUser):
    """ One user presents artist / store. """

    objects = UserManager()

    def get_absolute_url(self):
        return "/"

    def get_default_store(self):
        """ Get the store where this user is uploading content etc.

        One user can have several stores, but this always returns the first sone."
        """
        if self.is_superuser:
            return Store.objects.all().first()
        else:
            # Assume others have specific stores
            return self.operated_stores.first()

    def get_stores(self):
        """Return queryset of stores operated by this user.

        Admin gets snapshot of latest stores.
        """
        if self.is_superuser:
            return Store.objects.all()
        else:
            # Assume others have specific stores
            return self.operated_stores.all()

    def __str__(self):
        return self.username


class Store(models.Model):
    """ One user presents artist / store. """

    #: Which users can edit data for this artist
    operators = models.ManyToManyField(User, related_name="operated_stores")

    objects = UserManager()

    #: Visible in URls
    slug = AutoSlugField(populate_from='name')

    name = models.CharField(max_length=80, blank=True, null=True)

    #: In which fiat currency the sales of these songs are
    currency = models.CharField(max_length=5, blank=False, null=False, default="USD", verbose_name="Currency", help_text="Currency code for your local currency which you user to price your albums and songs", validators=[validate_currency])

    #: Where this store is hosted (needed for the backlinks)
    store_url = models.URLField(verbose_name="Homepage", help_text="Link to home page or Facebook page")

    #: The address where completed downlaod payments are credited
    btc_address = models.CharField(verbose_name="{} address".format(settings.COIN_NAME),
                                   help_text="Receiving address where the purchases will be credited. If you do not have cryptocurrency wallet yet you can leave this empty - the site will keep your coins until you get your own wallet.",
                                   max_length=50,
                                   blank=True,
                                   null=True,
                                   default=None)

    extra_html = models.TextField(verbose_name="Store style codes",
                                  help_text="Style the store page with CSS and HTML. Please ask your webmaster for the details.",
                                  default="",
                                  blank=True,
                                  null=True)

    extra_facebook_html = models.TextField(verbose_name="Facebook style codes",
                                  help_text="Style the Facebook store page with CSS and HTML. Please ask your webmaster for the details.",
                                  default="",
                                  blank=True,
                                  null=True)


    #: Data needed for the Facebook integration
    facebook_data = JSONField(verbose_name="Facebook page info", default={})

    def __str__(self):
        return self.name

    @property
    def email(self):
        """ Return the email where we should send notifications regarding this store. """
        if self.operators.all().count() > 0:
            return self.operators.all()[0].email
        return None

    @classmethod
    def find_by_facebook_page_id(self, page_id):
        # XXX: Add index for this
        for s in Store.objects.all().filter(facebook_data__isnull=False):
            tabs = s.facebook_data.get("tabs_added")
            if tabs:
                if tabs.get(page_id) is True:
                    return s

        return None


class StoreItem(models.Model):
    """ Base class for buyable content. """

    store = models.ForeignKey(Store)

    uuid = models.CharField(max_length=64, editable=False, blank=True, default=uuid4)

    #: Visible in URls
    slug = AutoSlugField(populate_from='name')

    name = models.CharField(max_length=80, blank=True, null=True)

    #: Price in store currency
    fiat_price = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal(0), validators=[validators.MinValueValidator(Decimal('0.01'))],
                                     verbose_name="Price")

    #: Hidden items are "soft-deleted" - they do not appear in the store,
    #: but still exist in db for accounting purposes and such
    visible = models.BooleanField(default=True, verbose_name="Visible / deleted", help_text="Uncheck this to make the item disappear from your store. The site still retains the copy of this item for a while before it is permanently deleted.")

    class Meta:
        abstract = True

    def get_btc_price(self):
        """ """
        converter = get_rate_converter()
        try:
            return converter.convert(self.store.currency, settings.PAYMENT_CURRENCY.upper(), self.fiat_price)
        except btcaverage.UnknownCurrencyException as e:
            logger.exception("Could not convert from %s to %s", self.store.currency, settings.PAYMENT_CURRENCY)
            logger.exception(e)
            return Decimal(-1)


class Album(StoreItem):
    """ Album containing X songs.

    Has cover art. You can buy the whole album with the reduced price.
    """

    #: Store's description of this albums
    description = models.CharField(verbose_name="Tagline", help_text="Short shout about the album shown in the album listing", max_length=40, blank=True, null=True)

    genre = models.IntegerField(verbose_name="Music genre", choices=GENRES, null=True, blank=True)

    cover = ThumbnailerImageField(upload_to=filename_gen("covers/"), blank=True, null=True,
                                  verbose_name="Cover art",
                                  help_text="Cover art as JPEG file")

    #: Full album as a zipped file
    download_zip = models.FileField(upload_to=filename_gen("songs/"), blank=True, null=True,
                                    verbose_name="Album download ZIP",
                                    help_text="A ZIP file which the user can download after he/she has paid for the full album")

    def get_download_info(self):
        _file = self.download_zip
        download_name = self.name + ".zip"
        content_type = "application/zip"
        return content_type, download_name, _file

    def get_visible_songs(self):
        return self.song_set.filter(visible=True)

    def get_genre(self):
        """Get human-readable genre name or None if not defined."""
        return GENRES_DICT.get(self.genre)

    def __str__(self):
        return "%s: %s" % (self.store.name, self.name)


class Song(StoreItem):
    """
    """

    #: Song can belong to album, or exist without an album
    album = models.ForeignKey(Album, null=True, blank=True,
                              verbose_name="Album",
                              help_text="On which album this song belongs to. Leave empty for an albumless song. (You can reorder the songs when you edit the album after uploading the songs.)")

    download_mp3 = models.FileField(upload_to=filename_gen("songs/"), blank=True, null=True,
                                    verbose_name="MP3 file",
                                    help_text="")

    prelisten_mp3 = models.FileField(upload_to=filename_gen("prelisten/"), blank=True, null=True,
                                     verbose_name="Prelisten clip MP3 file",
                                     help_text="For Safari and IE browsers. Leave empty: This will be automatically generated from uploaded song.")
    prelisten_vorbis = models.FileField(upload_to=filename_gen("prelisten/"), blank=True, null=True,
                                        verbose_name="Prelisten clip Ogg Vorbis file",
                                        help_text="For Chrome and Firefox browsers. Leave empty: This will be automatically generated from uploaded song.")

    #: Song duration in seconds
    duration = models.FloatField(blank=True, null=True)

    order = models.IntegerField(blank=True, null=True)

    class Meta:
        ordering = ('order', "-id")

    def get_download_info(self):
        _file = self.download_mp3
        content_type = "audio/mp3"
        download_name = self.name + ".mp3"
        return content_type, download_name, _file

    def __str__(self):
        return "%s: %s" % (self.store.name, self.name)


class DownloadTransaction(models.Model):
    """ Order to buy some songs, with attached bitcoin transaction info.
    """

    PAYMENT_SOURCE_BLOCKCHAIN = "blockchain.info"
    PAYMENT_SOURCE_BITCOIND = "bitcoind"
    PAYMENT_SOURCE_CRYPTOASSETS = "cryptoassets"

    #: Who we notify when the transaction is complete
    customer_email = models.CharField(max_length=64, blank=True, null=True)

    #: Django session used to create this purchase request
    session_id = models.CharField(max_length=64, blank=True, null=True)

    #: Human-readable description of this transaction
    description = models.CharField(max_length=256, editable=False, blank=True, default="")

    uuid = models.CharField(max_length=64, editable=False, blank=True, default=uuid4)

    store = models.ForeignKey(Store, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    #: The currency where the original prices where
    currency = models.CharField(max_length=5, blank=True, null=True)

    #: The currency used to display the prices to the user for this transaction
    user_currency = models.CharField(max_length=5, blank=True, null=True)

    #: The address where the owner must make the payment.
    btc_address = models.CharField(max_length=50, blank=True, null=True)

    # How many BTC was this order
    btc_amount = models.DecimalField(max_digits=16, decimal_places=8, default=Decimal(0))

    #: What's the source price of this transaction
    fiat_amount = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal(0))

    #: Either "blockchain.info" or "bitcoind"
    payment_source = models.CharField(max_length=32, blank=False, null=False)

    btc_received_at = models.DateTimeField(blank=True, null=True)

    #: For manual fixing missing BTC transfers
    manually_confirmed_received_at = models.DateTimeField(blank=True, null=True)

    #: Bitcoin transcation hash which triggered this payment complete
    received_transaction_hash = models.CharField(max_length=256, blank=True, null=True)

    #: The user pressed cancel on the payment page
    cancelled_at = models.DateTimeField(blank=True, null=True)

    #: If we don't receive payment by this time the payment
    #: can be considered as discarded
    expires_at = models.DateTimeField(blank=True, null=True)

    #: When this transaction was discarded
    expired_at = models.DateTimeField(blank=True, null=True)

    # Track where the orders are coming from
    # for the support
    ip = models.IPAddressField(blank=True, null=True)

    #: When this transaction was credited to the store owner
    credited_at = models.DateTimeField(blank=True, null=True)

    #: Bitcoin transaction id for the crediting payment
    credit_transaction_hash = models.CharField(max_length=256, blank=True, null=True)

    class Meta:
        verbose_name = "Purchase"
        verbose_name_plural = "Purchases"

    def __str__(self):
        return "store:{} uuid:{} addr:{} amount:{} txid:{}".format(self.store, self.uuid, self.btc_address, self.btc_amount, self.credit_transaction_hash)

    def update_new_btc_address(self):
        if self.payment_source == DownloadTransaction.PAYMENT_SOURCE_BLOCKCHAIN:
            self.update_new_btc_address_blockchain()
        elif self.payment_source == DownloadTransaction.PAYMENT_SOURCE_CRYPTOASSETS:
            self.update_new_btc_address_cryptoasset()
        else:
            raise RuntimeError("Unknown payment soucre")

    def update_new_btc_address_blockchain(self):
        """ Get blockchain.info payment address for this order.
        """
        from . import blockchain
        label = self.description + " Total: %s %s Order: %s" % (self.fiat_amount, self.currency, self.uuid)
        self.btc_address = blockchain.create_new_receiving_address(label=label)
        return self.btc_address

    def update_new_btc_address_cryptoasset(self):
        """ Get blockchain.info payment address for this order.
        """
        from . import payment
        label = self.description + " Total: %s %s Order: %s" % (self.fiat_amount, self.currency, self.uuid)
        self.btc_address = payment.create_new_receiving_address(self.store.id, label)
        return self.btc_address

    def prepare(self, items, description, session_id, ip, user_currency):
        """ Prepares this transaction for the payment phase.

        Count order total, initialize BTC addresses, etc.
        """
        self.ip = ip
        self.payment_source = settings.PAYMENT_SOURCE
        self.user_currency = user_currency
        self.expires_at = self.created_at + datetime.timedelta(days=1)
        self.session_id = session_id

        assert session_id, "Cannot create download transaction without a valid sessio"

        fiat_amount = Decimal(0)

        store = None
        source_currency = None

        for s in items:

            # Make sure everything is from the same artist,
            # as currently artist determinates the currency
            if not store:
                store = s.store
            else:
                assert s.store == store, "Cannot order cross artists (song)"

            fiat_amount += s.fiat_price
            source_currency = s.store.currency

            DownloadTransactionItem.objects.create(content_object=s, transaction=self)

        assert source_currency, "Did not get any line items"

        self.store = store
        self.currency = source_currency
        self.fiat_amount = fiat_amount

        converter = get_rate_converter()

        self.btc_amount = converter.convert(source_currency, settings.PAYMENT_CURRENCY.upper(), fiat_amount)

        self.description = description
        self.update_new_btc_address()

        # Make sure we don't accidentally create negative orders
        assert self.btc_amount > 0, "Cannot make empty or negative orders (btc) "
        assert self.fiat_amount > 0, "Cannot make empty or negative orders (fiat)"
        assert len(items) > 0, "At least one album or one song must be in the transaction"
        self.save()

    def is_pending(self):
        return self.btc_received_at is None and self.cancelled_at is None

    def is_completed(self):
        return self.btc_received_at is not None

    def is_credited(self):
        """ Has store owner been credited for this transation. """
        return False

    def is_cancelled(self):
        return self.cancelled_at is not None

    def get_status(self):
        """ Customer facing status. """
        if self.is_pending():
            return "pending"
        elif self.cancelled_at:
            return "cancelled"
        elif self.manually_confirmed_received_at:
            return "completed (manually marked)"
        else:
            return "completed"

    def mark_manually_confirmed(self):
        """ The user of a customer marks this BTC transaction manually confirmed. """
        self.manually_confirmed_received_at = timezone.now()
        self.btc_received_at = timezone.now()
        self.save()

    def mark_cancelled(self):
        """ The user of a customer marks this BTC transaction manually confirmed. """
        self.cancelled_at = timezone.now()
        self.save()

    def mark_payment_received(self):
        """ Enough Bitcoins have been received to process this transaction. """
        self.btc_received_at = timezone.now()
        content_manager = UserPaidContentManager(self.session_id)

        for download_item in DownloadTransactionItem.objects.filter(transaction=self):
            item = download_item.content_object
            content_manager.mark_paid_by_user(item, self)
        self.save()

    def get_notification_message(self):
        """ Return the notification payload used to async communication about this transcation. """
        return dict(transaction_uuid=str(self.uuid), status=self.get_status())

    def check_balance(self, value, transaction_hash):
        """ Check if this transaction can be confirmed as received.

        :param value: How much value the address of this transaction has now.

        :param transaction_hash: incoming transaction

        :return: True if there was enough balance to confirm this transaction.
        """
        t = self

        assert t.btc_received_at is None, "Already credited"

        if t.cancelled_at is None:
            # User fuck up
            logger.error("Crediting cancelled transaction %d", t.id)

        if value >= t.btc_amount - settings.TRANSACTION_BALANCE_CONFIRMATION_THRESHOLD_BTC:
            logger.info("TX payment success, address: %s tx: %s needed: %s got: %s", t.btc_address, transaction_hash, t.btc_amount, value)
            t.received_transaction_hash = transaction_hash
            self.mark_payment_received()
            return True
        elif value < t.btc_amount - settings.TRANSACTION_BALANCE_CONFIRMATION_THRESHOLD_BTC:
            logger.error("SHORT OF VALUE: Transaction receiving address: %s unconfirmed balance: %s needs: %s", t.btc_address, value, t.btc_amount)
            return False
        elif value == Decimal("0"):
            logger.error("Got notification for the transaction in address %s but unconfimed_balance() still zero", t.btc_address)
            return False
        else:
            raise RuntimeError("Unhandled transaction balance case %s %s %s" % transaction_hash, value, t.btc_address)


class DownloadTransactionItem(models.Model):
    """ All items which were bought with the particular transaction.

    Links DownloadTransaction to song/album using GenericRelationship.
    """
    transaction = models.ForeignKey(DownloadTransaction)
    content_type = models.ForeignKey(ContentType)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey()

    def get_download_info(self):
        """ Get content type and filename for the download. """
        item = self.content_object
        return item.get_download_info()

    def __str__(self):
        """Helper to troubleshoot issues."""
        item = self.content_object
        fitem = item.download_mp3 if hasattr(item, "download_mp3") else item.download_zip
        return "id:{} name:{} file:{}".format(item.id, item.name, os.path.basename(fitem.name))


class UserPaidContentManager(object):
    """ Remember which songs and albums are available for the user.

    We store the list in redis for the performance reason,
    as this list is retrieved for every store page view.

    This data expires in 365 days, because that's how long
    we store the session data maximum. After that the retrieval
    of items must be done through the support.
    """

    #: session id -> hash of content already owned
    #: hash maps "song_x" or "album_x" to DownloadTransaction id which has paid for the content
    REDIS_HASH_KEY = "session_paid_content"

    def __init__(self, session_id):
        assert session_id, "User content manager needs valid session for the user"
        self.redis = get_cache("default").client.get_client(write=True)
        self.session_id = session_id
        content = self.redis.hget(UserPaidContentManager.REDIS_HASH_KEY, session_id)
        if content:
            content = content.decode("utf-8")
            content = json.loads(content)
        else:
            content = {}
        self.content = content

    def get_download_transaction(self, uuid):
        """
        :param type: "album" or "song"
        """

        uuid = str(uuid)
        transaction_uuid = self.content.get(uuid)
        if not transaction_uuid:
            return None
        else:
            try:
                return DownloadTransaction.objects.get(uuid=transaction_uuid)
            except DownloadTransaction.DoesNotExist:
                return None

    def has_item(self, item):
        return self.get_download_transaction(item.uuid) is not None

    def mark_paid_by_user(self, item, transaction):
        assert isinstance(item, StoreItem)
        logger.info("Marking item paid %d %s", item.id, transaction.uuid)
        self.content[str(item.uuid)] = str(transaction.uuid)
        # Save back to redis
        self.redis.hset(UserPaidContentManager.REDIS_HASH_KEY, self.session_id, json.dumps(self.content).encode("utf-8"))


class WelcomeWizard(object):
    """Manage store set up wizard procedure."""

    #: username -> JSON'ed welcome step status dictionary
    REDIS_HASH_KEY = "user_welcome_wizard_steps"

    steps = ["check_store_details",
             "upload_album",
             "preview_store",
             "embed_website_store",
             "embed_facebook_store"]

    def __init__(self, store):
        self.redis = get_cache("default").client.get_client(write=True)
        assert isinstance(store, Store)
        self.store = store

    @classmethod
    def clear(self):
        """ Reset the state of all welcome wizards. """
        redis = get_cache("default").client.get_client(write=True)
        redis.delete(WelcomeWizard.REDIS_HASH_KEY)

    def _create_default_content(self):
        """ By default set all steps not completed. """
        content = {step: False for step in self.steps}
        return content

    def _update_content(self, content):
        self.redis.hset(WelcomeWizard.REDIS_HASH_KEY, self.store.name, json.dumps(content).encode("utf-8"))

    def get_step_statuses(self):
        """
        """
        content = self.redis.hget(WelcomeWizard.REDIS_HASH_KEY, self.store.name)

        if not content:
            content = self._create_default_content()
        else:
            if type(content) == bytes:
                content = content.decode("utf-8")
            content = json.loads(content)
        return content

    def set_step_status(self, step_id, status):
        """
        """
        content = self.get_step_statuses()
        assert step_id in content, "No step %s in %s" % (step_id, content)
        content[step_id] = status
        self._update_content(content)

