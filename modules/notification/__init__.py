import json
from modules.core.classy import FlaskView, route
from modules import cbpi
class NotificationView(FlaskView):

    @route('/', methods=['GET'])
    def getMessages(self):
        """
        Get all messages
        :return: current messages
        """

        return json.dumps(cbpi.cache["messages"])

    @route('/<id>', methods=['DELETE'])
    def dismiss(self, id):
        """
        Delete message from cache by id
        :param id: message id to be deleted
        :return: empty response HTTP 204

        Danach wird NOTIFY_DISMISS emittiert. Der Cache
        cbpi.cache["messages"] ist prozessweit - die Message ist nach dem
        DELETE wirklich fuer alle weg. Der Kern emittierte dabei aber
        nichts, die anderen Clients erfuhren es erst, wenn sie zufaellig
        neu luden (/api/system/dump beim reconnect). Bis dahin stand die
        Notification bei ihnen noch in der Liste, und der persistente Toast
        blieb komplett stehen, waehrend der Brauer, der sie weggeklickt hat,
        eine Liste ansah, in der sie nicht mehr ist. Handy in der einen
        Hand, Tablet an der Wand: das ist der Normalfall.
        """
        for idx, m in enumerate(cbpi.cache.get("messages", [])):
            if (m.get("id") == id):
                cbpi.cache["messages"].pop(idx)
        # Auch dann emittieren, wenn nichts gefunden wurde. Der Kern
        # antwortet in beiden Faellen 204, und ein Client, der gerade eine
        # bereits von einem anderen geloeschte Message wegklickt, muss
        # trotzdem bescheid wissen: die Notification, die er aus seiner
        # Liste fallen laesst, ist genau die, die er eben angeklickt hat.
        # Erst dadurch stimmen die beiden Listen ueberein.
        cbpi.emit("NOTIFY_DISMISS", id)
        return ('', 204)

@cbpi.event("MESSAGE", async_=True)
def messageEvent(message, **kwargs):
    """
    React on message event. add the message to the cache and push the message to the clients
    :param message: the message
    :param kwargs: other parameter
    :return: None
    """
    if message["timeout"] is None:
        cbpi.cache["messages"].append(message)
    cbpi.emit("NOTIFY", message)

@cbpi.initalizer(order=2)
def init(cbpi):
    """
    Initializer for the message module
    :param cbpi: the craftbeerpi instance
    """
    if cbpi.get_config_parameter("donation_notification", "YES") == "YES":
        msg = {"id": len(cbpi.cache["messages"]), "type": "info", "headline": "Support CraftBeerPi with your donation", "message": "You will find the PayPay Donation button in the system menu" , "read": False}
        cbpi.cache["messages"].append(msg)

    NotificationView.register(cbpi.app, route_base='/api/notification')
