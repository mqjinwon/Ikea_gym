import gdown
import os

demos = {
    'Sawyer_bench_bjursta_0210_00XX.zip': '1uGeamzI5VkNNjCITSpitg-BivcIiQ0iB',
    'Sawyer_bench_bjursta_0210_001X': '1RwzSFn1dRDkWfd9dWmKRZNav8B43H6tP',
    'Sawyer_table_bjorkudden_0207_00XX.zip': '1tUyLxpUo_IFakgXtRFPNjI3u6ISTMIQz',
    'Sawyer_table_bjorkudden_0207_10XX.zip': '1shslsnTYSyscJyEXwRWFVHWFo4Ruj10Y',
    'Sawyer_table_lack_0825_00XX.zip': '1IN_H79aa9ndcuckmpXXlEJcoKEzKFLN-',
    'Sawyer_table_lack_0825_10XX.zip': '1gCeiJ2XN5O5acudxq37A3JQqg162vO4R',
    'Sawyer_toy_table_00XX.zip': '14F-6wgVpz3P_sGhJlU7gKZ-qFTcDySzH',
    'Sawyer_toy_table_01XX.zip': '16gRRYaLLJwrWLhUuI0v8y_9FW7nbqqCs',
    'Sawyer_table_dockstra_0279_00XX.zip': '1UOkgSBgIa34cRKySCpwstxJ0IpDcYnGQ',
    'Sawyer_table_dockstra_0279_01XX.zip': '1wusFZLDsq9DCRf_U9DEPnjSdmWvrgY3U',
    'Sawyer_chair_agne_0007_00XX.zip': '1a7E8QH4BRTHCwJ_0qfNKcoGOzdrH8qgR',
    'Sawyer_chair_agne_0007_01XX.zip': '1YfnoxhZbqxZciQ6-CnPhHM_v43-m6xzQ',
    'Sawyer_chair_ingolf_0650_00XX.zip': '1dnXBiWVKVJK_uhUxHC4ecxnyWqv-HvRi',
    'Sawyer_chair_ingolf_0650_01XX.zip': '1Pw65zAF78ZoGLR0WpkcygfuoIO9a_xrL'
}

# url = 'https://drive.google.com/uc?id=' + unique google drive ID
# compression format = '.zip'

for key, value in demos.items():
    url = 'https://drive.google.com/uc?id=' + value
    outfile = os.path.join('demos', key)
    if os.path.exists(outfile):
        print('already downloaded', outfile)
    else:
        gdown.download(url, outfile, quiet=False)