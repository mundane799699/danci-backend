from xhs_utils import Xhshow

client = Xhshow()


def post_xs(api, a1_value, data):
    signature = client.sign_xs_post(uri=api, a1_value=a1_value, payload=data)
    return signature


def get_xs(api, a1_value, data):
    signature = client.sign_xs_get(uri=api, a1_value=a1_value, params=data)
    return signature
