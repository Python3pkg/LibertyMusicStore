(function($) {

    "use strict";

    var paymentProgress = 0;
    var pymChild = null;

    // http://stackoverflow.com/a/13164238/315168
    function writeCookie(key, value, days) {
        var date = new Date();
        // Get unix milliseconds at current time plus number of days
        date.setTime(+date + (days * 86400000)); //24 * 60 * 60 * 1000
        window.document.cookie = key + "=" + '"' + value + '"' + "; expires=" + date.toGMTString() + "; path=/";
        return value;
    }

    /**
     * Totally psychological progress bar.
     */
    function updatePaymentProgress() {
        paymentProgress += 0.1;
        if(paymentProgress >= 100) {
            paymentProgress = 0; // Wrap around
        }
        $("#payment-progress .progress-bar").css("width", paymentProgress+"%");
    }

    /**
     * Handle <iframe> embed and signalling with the parent frame.
     */
    function initEmbed() {
        pymChild = new pym.Child({id: "store-embed-iframe-wrapper"});

        $(window).load(function() {
            console.log("foo");
            pymChild.sendHeightToParent();
        });
    }

    /**
     * Load the library.
     */
    function initBitcoinAddresses() {
        // Basic initialization
        bitcoinaddress.init({
            // jQuery selector defining bitcon addresses on the page
            // needing the boost
            selector: ".bitcoin-address",

            // Id of the DOM template element we use to decorate the addresses.
            // This must contain placefolder .bitcoin-address
            template: "bitcoin-address-template",

            generateQREagerly: true,

            // Passed directly to QRCode.js
            // https://github.com/davidshimjs/qrcodejs
            qr : {
                width: 128,
                height: 128,
                colorDark : "#000000",
                colorLight : "#ffffff"
            }
        });
    }

    function pollTransaction() {

        if(!window.poll) {
            return;
        }

        function repoll() {
            console.log("Starting long-poll again");
            window.setTimeout(pollTransaction, 10);
        }

        var transactionUUID = window.poll.transactionUUID;
        var url = window.poll.pollURL;
        var nextURL = window.poll.nextURL;

        var buster = Math.random();

        console.log("Transaction long poll to ", url);

        $.ajax({
            url: url,
            data: {"cache-buster": buster},
            success: function(data) {

                // 304 not modified
                if(!data) {
                    repoll();
                    return;
                }

                // We get notification related to this transaction, go forward
                console.log(data);
                data = JSON.parse(data);
                if(data.transaction_uuid == transactionUUID) {
                    window.location = nextURL;
                } else {
                    // Another transaction for this customer
                    repoll();
                }
            },
            error: function(xhr) {
                console.log(xhr);
                alert("Error communicating with the server.");
            }
        });
    }

    function initPrices() {
        bitcoinprices.init({

            // Where we get bitcoinaverage data
            // or null if we run headless (not in browser)
            url: "https://api.bitcoinaverage.com/ticker/all",

            // Which of bitcoinaverages value we use to present prices
            marketRateVariable: "24h_avg",

            // Which currencies are in shown to the user
            currencies: ["BTC", "USD", "EUR", "GBP"],

            // Special currency symbol artwork
            symbols: {
                "BTC": "<i class='fa fa-btc'></i>",
                "USD": "$",
                "EUR": "€",
                "GBP": "£"
            },

            // Which currency we show user by the default if
            // no currency is selected
            defaultCurrency: "BTC",

            // We don't have clickable price features
            // in the store
            clickablePriceSelector: ".foobar",

            // How the user is able to interact with the prices
            ux : {
                // Make everything with data-btc-price HTML attribute clickable
                clickPrices : true,

                // Build Bootstrap dropdown menu for currency switching
                menu : true,

                clickableCurrencySymbol: false
            },

            // Allows passing the explicit jQuery version to bitcoinprices.
            // This is useful if you are using modular javascript (AMD/UMD/require()),
            // but for most normal usage you don't need this
            jQuery: jQuery
        });
    }

    /**
     * Cycle through available currencies
     */
    function handleCurrencySwitch() {
        $("#change-currency").click(function() {
            var currency  = bitcoinprices.toggleNextActiveCurrency();
            $(document).trigger("activecurrencychange");

            // Pass information to the server what currency the user is suing
            writeCookie("user_currency", currency, 30);
        });
    }

    /**
     * Artist page JS entry point.
     */
    function handlePlayAndOrder() {
        var currentlyPlaying = null;

        $(".btn-prelisten").click(function(e) {

            e.preventDefault();

            function stopPlaying() {

                if(currentlyPlaying) {
                    audiotools.fadeOut(currentlyPlaying);
                    //currentlyPlaying.pause();
                    currentlyPlaying = null;
                }
                // Revert icons to normal
                $(".btn-prelisten i").attr("class", "fa fa-volume-up");
                $(".btn-prelisten").removeClass("playing");
            }


            var btn = $(this);

            var isStopAction = btn.hasClass("playing");

            // Revert all icons back
            stopPlaying();

            if(isStopAction) {
                // don't start again
                return;
            }

            // Show spinner until loaded
            btn.addClass("playing");
            btn.find("i").attr("class", "fa fa-spin fa-spinner");

            var audio = btn.parents(".song").find("audio").get(0);

            $(audio).on("playing", function() {
                btn.find("i").attr("class", "fa fa-stop");
            });

            $(audio).on("canplay", function() {
                //btn.find("i").attr("class", "fa fa-stop");
                audiotools.fadeIn(currentlyPlaying);
            });

            $(audio).on("ended", function() {
                stopPlaying();
            });


            currentlyPlaying = audio;
            audio.load();

            return false;
        });
    }

    /**
     * Make BTC amount clickable
     */
    function initClickableAmount() {
        $(".btc-clickable-amount").click(function() {
            window.getSelection().selectAllChildren(this);
        });
    }

    $(document).ready(function() {
        initEmbed();
        initPrices();
        initClickableAmount();
        initBitcoinAddresses();
        window.setInterval(updatePaymentProgress, 500);
        pollTransaction();
        handlePlayAndOrder();
        handleCurrencySwitch();
    });

})(jQuery);
