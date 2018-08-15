#!/usr/bin/python
# -*- coding: utf-8 -*-

import sys
import os
import requests
import argparse
import logging
import yaml
from config.config import Config
from subprocess import Popen, PIPE

c = Config

def get_module_logger(mod_name):
    '''
    define a common logger template to record log.
    @param mod_name log module name.
    @return logger.
    '''
    logger = logging.getLogger(mod_name)
    logger.setLevel(logging.DEBUG)
    # 设置日志文件handler，并设置记录级别
    fh = logging.FileHandler("hadoop_exporter.log")
    fh.setLevel(logging.ERROR)

    # 设置终端输出handler，并设置记录级别
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)

    # 设置日志格式
    fmt = logging.Formatter(fmt='%(asctime)s %(filename)s[line:%(lineno)d]-[%(levelname)s]: %(message)s')
    fh.setFormatter(fmt)
    sh.setFormatter(fmt)

    # 添加handler到logger对象
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger

logger = get_module_logger(__name__)

def get_metrics(url):
    '''
    :param url: The jmx url, e.g. http://host1:50070/jmx,http://host1:8088/jmx, http://host2:19888/jmx...
    :return a dict of all metrics scraped in the jmx url.
    '''
    try:
        response = requests.get(url, auth=("admin", "admin"), timeout=5)  # , params=params, auth=(self._user, self._password))
    except Exception as e:
        logger.error(e)
    else:    
        if response.status_code != requests.codes.ok:
            logger.error("Get {0} failed, response code is: {1}.".format(url, response.status_code))
            return []
        result = response.json()
        logger.debug(result)
        if result and "beans" in result:
            return result
        else:
            logger.error("No metrics get in the {0}.".format(url))
            return []

def read_json_file(path_name, file_name):
    '''
    read metric json files.
    '''
    path = os.path.dirname(os.path.realpath(__file__))
    metric_path = os.path.join(path, path_name)
    metric_name = "{0}.json".format(file_name)
    try:
        with open(os.path.join(metric_path, metric_name), 'r') as f:
            metrics = yaml.safe_load(f)
            return metrics
    except Exception as e:
        logger.error("read metrics json file failed, error msg is: %s" %e)
        sys.exit(1)


def get_url_list():

    url_list = []
    items = vars(Config).items()
    tmp = dict(items)
    for k,v in tmp.items():
        if "URL" in k:
            url_list.append(v)
    return url_list


def get_config_file():
    '''
    Get config file generated by consul-template with an template file
    @return a dict of config or exit with system status=1
    '''
    path = os.path.dirname(os.path.realpath(__file__))
    tpl_file = path + "/config/config.tpl"
    config_file = path + "/config/config.conf"
    # generate config file
    output = Popen(['/usr/local/bin/consul-template -template="' + tpl_file + ':' + config_file + '" -once'],
                   stdout=PIPE,
                   stderr=PIPE,
                   shell=True)
    output.communicate()
    if output.returncode == 0:
        file = config_file
    else:
        logger.error("Cannot generate config file, please check consul-template or template file.")
        sys.exit(1)

    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
        return config

def get_config_from_file():
    path = os.path.dirname(os.path.realpath(__file__))
    config_file = path + "/config/config.conf"
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
        return config

def get_ambari_url():
    '''
    Get available ambari url from consul using consul-template
    @return a string of avaliable ambari url or None if no avaliable url.
    '''
    config = get_config_file()
    # config = get_config_from_file()
    if 'ip' in config.keys():
        if 'proxy_port' in config.keys():
            avaliable_url = "http://{}:{}".format(config['ip'][0], config['proxy_port'])
        elif 'port' in config.keys():
            avaliable_url = "http://{}:{}".format(config['ip'][0], config['port'][0])
        else:
            logger.error("No avaliable port in config file.")
            return None
    else:
        logger.error("No avaliable ip in config file.")
        return None
    return avaliable_url

def get_cluster_name():
    '''
    Get cluster via ambari REST API
    @return a list of cluster name
    '''
    cluster_list = []
    ambari_url = get_ambari_url()
    cluster_url = "{0}/api/v1/clusters?fields=Clusters/cluster_name".format(ambari_url)
    try:
        response = requests.get(cluster_url, auth=("admin", "admin"), timeout=5)  # , params=params, auth=(self._user, self._password))
    except Exception as e:
        logger.error(e)
    else:    
        if response.status_code != requests.codes.ok:
            logger.error("Get {0} failed, response code is: {1}.".format(cluster_url, response.status_code))
            return None
        result = response.json()
        logger.debug(result)
        if result and "items" in result and result['items']:
            for i in range(len(result['items'])):
                cluster_list.append(result['items'][i]['Clusters']['cluster_name'])
            return cluster_list
        else:
            logger.error("No metrics get in the {0}.".format(cluster_url))
            return None



def get_active_hdfs_url(cluster):
    '''
    Using ambari API to get Active component.
    @param cluster: cluster name.
    @param component: component name, e.g. namenode
    @return a list of ACTIVE host name.
    '''
    ambari_url = get_ambari_url()
    hdfs_url = []
    url = "{0}/api/v1/clusters/{1}/host_components?HostRoles/component_name=NAMENODE&metrics/dfs/FSNamesystem/HAState=active".format(ambari_url, cluster)
    try:
        response = requests.get(url, auth=("admin", "admin"), timeout=5)  # , params=params, auth=(self._user, self._password))
    except Exception as e:
        logger.error(e)
    else:    
        if response.status_code != requests.codes.ok:
            logger.error("Get {0} failed, response code is: {1}.".format(url, response.status_code))
            return None
        result = response.json()
        logger.debug(result)
        if result and "items" in result and result['items']:
            hdfs_url.append("http://{0}:50070/jmx".format(result['items'][0]['HostRoles']['host_name']))
            return hdfs_url
        else:
            logger.error("No metrics get in the {0}.".format(url))
            return None

def get_active_hbase_url(cluster):
    '''
    Using ambari API to get Active component.
    @param cluster: cluster name.
    @param component: component name, e.g. namenode
    @return a list of ACTIVE host name.
    '''
    ambari_url = get_ambari_url()
    hbase_url = []
    url = "{0}/api/v1/clusters/{1}/host_components?HostRoles/component_name=HBASE_MASTER&metrics/hbase/master/IsActiveMaster=true".format(ambari_url, cluster)
    try:
        response = requests.get(url, auth=("admin", "admin"), timeout=5)  # , params=params, auth=(self._user, self._password))
    except Exception as e:
        logger.error(e)
    else:    
        if response.status_code != requests.codes.ok:
            logger.error("Get {0} failed, response code is: {1}.".format(url, response.status_code))
            return None
        result = response.json()
        logger.debug(result)
        if result and "items" in result and result['items']:
            hbase_url.append("http://{0}:16010/jmx".format(result['items'][0]['HostRoles']['host_name']))
            return hbase_url
        else:
            logger.error("No metrics get in the {0}.".format(url))
            return None

def get_active_rm_url(cluster):
    '''
    Get active resource manager url via ambari REST API
    @param cluster: a string of cluster name
    @return a list of an active resourcemanager url
    '''
    hosts = get_available_nodes(cluster, "YARN", "resourcemanager")
    rm_url = []
    success = 0
    for i in range(len(hosts)):
        url = "http://{0}:8088/ws/v1/cluster/info".format(hosts[i])
        try:
            response = requests.get(url, auth=("admin", "admin"), timeout=5)  # , params=params, auth=(self._user, self._password))
        except Exception as e:
            logger.error(e)
        else:    
            if response.status_code != requests.codes.ok:
                logger.error("Get {0} failed, response code is: {1}.".format(url, response.status_code))
                continue
            result = response.json()
            logger.debug(result)
            if result and "clusterInfo" in result and result['clusterInfo']:
                if 'haState' in result['clusterInfo'] and 'ACTIVE' == result['clusterInfo']['haState']:
                    rm_url.append("http://{0}:8088/jmx".format(hosts[i]))
                    success += 1
                    return rm_url
                else:
                    logger.debug("haState not ACTIVE, try another node.")
                    continue
            else:
                logger.error("No metrics get in the {0}.".format(url))
                continue
    if not success:
        logger.error("Cannot get active resourcemanager url from /ws/v1/cluster/info")
        return None

def get_available_nodes(cluster, component, service):
    '''
    Get available nodes via ambari REST API
    @param cluster: a string of cluster name
    @param component: a string of component name, e.g. "HDFS", "YARN", "HBASE"...
    @param service: a string of service name, e.g. "namenode", "datanode", "journalnode"....    
    @return a list of available nodes scraped from ambari REST API
    '''
    component_upper = component.upper()
    service_upper = service.upper()
    ambari_url = get_ambari_url()
    hosts = []
    url = "{0}/api/v1/clusters/{1}/services/{2}/components/{3}?fields=host_components/HostRoles/host_name".format(ambari_url, cluster, component_upper, service_upper)
    try:
        response = requests.get(url, auth=("admin", "admin"), timeout=5)  # , params=params, auth=(self._user, self._password))
    except Exception as e:
        logger.error(e)
    else:    
        if response.status_code != requests.codes.ok:
            logger.error("Get {0} failed, response code is: {1}.".format(url, response.status_code))
            return None
        result = response.json()
        logger.debug(result)
        if result and "host_components" in result and result['host_components']:
            for i in range(len(result['host_components'])):
                hosts.append(result['host_components'][i]['HostRoles']['host_name'])
            return hosts
        else:
            logger.error("No metrics get in the {0}.".format(url))
            return None

def get_node_url(hosts, port):
    '''
    Get node url by putting hosts and port together.
    @param hosts: a list of hosts running different services
    @param port: a string of jmx port running on
    @return a list of jmx url
    '''
    node_url = []
    for i in range(len(hosts)):
        url = "http://{0}:{1}/jmx".format(hosts[i], port)
        node_url.append(url)
    return node_url

def get_datanode_url(cluster):
    '''
    @return a list of datanode jmx url in a default port 1022
    '''
    hosts = get_available_nodes(cluster, "HDFS", "datanode")
    datanode_url = get_node_url(hosts, "1022")
    return datanode_url

def get_journalnode_url(cluster):
    '''
    @return a list of datanode jmx url in a default port 1022
    '''
    hosts = get_available_nodes(cluster, "HDFS", "journalnode")
    journalnode_url = get_node_url(hosts, "8480")
    return journalnode_url

def get_mapreduce2_url(cluster):
    '''
    @return a list of mapreduce2 jmx url on a default port 19888
    '''
    hosts = get_available_nodes(cluster, "MAPREDUCE2", "HISTORYSERVER")
    mapreduce2_url = get_node_url(hosts, "19888")
    return mapreduce2_url


def get_file_list(file_path_name):
    '''
    This function is to get all .json file name in the specified file_path_name.
    @param file_path: The file path name, e.g. namenode, ugi, resourcemanager ...
    @return a list of file name.
    '''
    path = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(path, file_path_name)
    try:
        files = os.listdir(json_path)
    except OSError:
        logger.error("No such file or directory: '%s'" %json_path)
        return []
    else:
        rlt = []
        for i in range(len(files)):
            rlt.append(files[i].split(".")[0])
        return rlt


def parse_args():

    parser = argparse.ArgumentParser(
        description = 'hadoop node exporter args, including url, metrics_path, address, port and cluster.'
    )
    parser.add_argument(
        '-c','--cluster',
        choices = get_cluster_name(),
        required = False,
        # dest = 'cluster',
        metavar = 'cluster_name',
        help = 'Hadoop cluster labels. (default "{0}")'.format(get_cluster_name()[0]),
        default = get_cluster_name()[0]
    )
    parser.add_argument(
        '-hdfs', '--namenode-url',
        choices = get_active_hdfs_url(get_cluster_name()[0]),
        required=False,
        metavar='namenode_jmx_url',
        help='Hadoop hdfs metrics URL. (default "{0}")'.format(get_active_hdfs_url(get_cluster_name()[0])[0]),
        default=get_active_hdfs_url(get_cluster_name()[0])[0]
    )
    parser.add_argument(
        '-rm', '--resourcemanager-url',
        choices = get_active_rm_url(get_cluster_name()[0]),
        required=False,
        metavar='resourcemanager_jmx_url',
        help='Hadoop resourcemanager metrics URL. (default "{0}")'.format(get_active_rm_url(get_cluster_name()[0])[0]),
        default=get_active_rm_url(get_cluster_name()[0])[0]
    )
    parser.add_argument(
        '-dn', '--datanode-url',
        choices = get_datanode_url(get_cluster_name()[0]),
        required=False,
        metavar='datanode_jmx_url',
        help='Hadoop datanode metrics URL. (default "{0}")'.format(get_datanode_url(get_cluster_name()[0])[0]),
        default=get_datanode_url(get_cluster_name()[0])[0]
    )
    parser.add_argument(
        '-jn', '--journalnode-url',
        choices = get_journalnode_url(get_cluster_name()[0]),
        required=False,
        metavar='journalnode_jmx_url',
        help='Hadoop journalnode metrics URL. (default "{0}")'.format(get_journalnode_url(get_cluster_name()[0])[0]),
        default=get_journalnode_url(get_cluster_name()[0])[0]
    )
    parser.add_argument(
        '-mr', '--mapreduce2-url',
        choices = get_mapreduce2_url(get_cluster_name()[0]),
        required=False,
        metavar='mapreduce2_jmx_url',
        help='Hadoop mapreduce2 metrics URL. (default "{0}")'.format(get_mapreduce2_url(get_cluster_name()[0])[0]),
        default=get_mapreduce2_url(get_cluster_name()[0])[0]
    )
    parser.add_argument(
        '-hbase', '--hbase-url',
        choices = get_active_hbase_url(get_cluster_name()[0]),
        required=False,
        metavar='hbase_jmx_url',
        help='Hadoop hbase metrics URL. (default "{0}")'.format(get_active_hbase_url(get_cluster_name()[0])[0]),
        default=get_active_hbase_url(get_cluster_name()[0])[0]
    )
    parser.add_argument(
        '-hive', '--hive-url',
        choices = get_url_list(),
        required=False,
        metavar='hive_jmx_url',
        help='Hadoop hive metrics URL. (default "http://ip:port/jmx")',
        default=c.HIVE_URL
    )
    parser.add_argument(
        '-p','--path',
        metavar='metrics_path',
        required=False,
        help='Path under which to expose metrics. (default "/metrics")',
        default='/metrics'
    )
    parser.add_argument(
        '-host','-ip','--address','--addr',
        metavar='ip_or_hostname',
        required=False,
        type=str,
        help='Polling server on this address. (default "127.0.0.1")',
        default='127.0.0.1'
    )
    parser.add_argument(
        '-P', '--port',
        metavar='port',
        required=False,
        type=int,
        help='Listen to this port. (default "9131")',
        default=9131
    )
    return parser.parse_args()


def main():
    '''
    config = Config()
    url = config.BASE_URL
    address = config.DEFAULT_ADDR
    port = config.DEFAULT_PORT
    parsejobs(url)
    logger.info("utils.py info msg.")
    '''
    # url = []
    # items = vars(Config).items()
    # tmp = dict(items)
    # keys = filter(lambda k:"URL" in k, tmp.keys())
    # print keys
    # for k in keys:
    #     url.append(tmp[k])
    # print [lambda k:tmp[k] for k in keys]
    # print [lambda v:v for k,v in tmp.items if "URL" in k]
    
    # print url
    # args = parse_args()
    # print args.address
    print parse_args()
    print get_file_list("namenode")
    print get_file_list("resourcemanager")
    print "=============================="
    print get_ambari_url()
    cluster = get_cluster_name()
    print cluster[0]
    print get_active_hdfs_url(cluster[0])
    print get_active_rm_url(cluster[0])
    print get_active_hbase_url(cluster[0])
    print get_datanode_url(cluster[0])
    print get_journalnode_url(cluster[0])
    print get_mapreduce2_url(cluster[0])
    print "=============================="
    print get_file_list("common")
    pass

if __name__ == '__main__':
    main()