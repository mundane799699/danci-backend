from xhs_utils import Xhshow

client = Xhshow()

cookies = {
    'abRequestId': 'e14efee3-e512-5e48-bcee-7d3340dff7ab',
    'a1': '19223bd30fdyw4izqnvssalktamaab9jcq1a9gdne50000166530',
    'webId': '89daffcfb24ae99c9b86c49c47aa5f14',
    'gid': 'yjJJqDf4K2SKyjJJqDfq8AkfifvE43uAIhMMyId01T90602800DjVj888yKK2q88djSWK0Yj',
    'x-user-id-pgy.xiaohongshu.com': '66b8e282e200000000000001',
    'customerClientId': '181081597890792',
    'x-user-id-creator.xiaohongshu.com': '5f827ea10000000001007b5b',
    'xsecappid': 'xhs-pc-web',
    'webBuild': '4.75.2',
    'web_session': '0400698ef63de9562b0de408a63a4b238d5b85',
    'unread': '{%22ub%22:%226891387f000000002203ad19%22%2C%22ue%22:%226892c1290000000023025ac4%22%2C%22uc%22:28}',
    'acw_tc': '0ad62c8617544828392536663e807edf46f0f475681b4b929cc3d22c40e8bc',
    'websectiga': 'cffd9dcea65962b05ab048ac76962acee933d26157113bb213105a116241fa6c',
    'sec_poison_id': 'e9e7eadd-a49b-42a1-86c9-cbd4b9311521',
    'loadts': '1754484230164',
}

headers = {
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
    'cache-control': 'no-cache',
    'origin': 'https://www.xiaohongshu.com',
    'pragma': 'no-cache',
    'priority': 'u=1, i',
    'referer': 'https://www.xiaohongshu.com/',
    'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-site',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
    # 'cookie': 'abRequestId=e14efee3-e512-5e48-bcee-7d3340dff7ab; a1=19223bd30fdyw4izqnvssalktamaab9jcq1a9gdne50000166530; webId=89daffcfb24ae99c9b86c49c47aa5f14; gid=yjJJqDf4K2SKyjJJqDfq8AkfifvE43uAIhMMyId01T90602800DjVj888yKK2q88djSWK0Yj; x-user-id-pgy.xiaohongshu.com=66b8e282e200000000000001; customerClientId=181081597890792; x-user-id-creator.xiaohongshu.com=5f827ea10000000001007b5b; xsecappid=xhs-pc-web; webBuild=4.75.2; web_session=0400698ef63de9562b0de408a63a4b238d5b85; unread={%22ub%22:%226891387f000000002203ad19%22%2C%22ue%22:%226892c1290000000023025ac4%22%2C%22uc%22:28}; acw_tc=0ad62c8617544828392536663e807edf46f0f475681b4b929cc3d22c40e8bc; websectiga=cffd9dcea65962b05ab048ac76962acee933d26157113bb213105a116241fa6c; sec_poison_id=e9e7eadd-a49b-42a1-86c9-cbd4b9311521; loadts=1754484230164',
}


def post_xs(api, a1_value, data):
    signature = client.sign_xs_post(
        uri=api,
        a1_value=a1_value,
        payload=data
    )
    return signature


def get_xs(api, a1_value, data):
    signature = client.sign_xs_get(
        uri=api,
        a1_value=a1_value,
        params=data
    )
    return signature
