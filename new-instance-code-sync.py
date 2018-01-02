from __future__ import print_function
from dateutil.parser import parse
from datetime import datetime
import json
import time
import os
import boto3
ec2client = boto3.client('ec2')
client = boto3.client('codedeploy')
codedeployrole = os.environ.get("CodeDeployRole")

""" Main method controlling the sequence of actions as follows
        1. Parses EC2 Launch event
        2. Checks whether its a Spot EC2 Instance or an on-demand instance
        3. For Spot Instance, it looks up the Tags from the request and propagates them to the Spot Instance
        4. Based on the CodeDeployApplication, CodeDeployDeploymentGroup and Name Tag, it adds the EC2 Instance to its respective CodeDeploy Deployment Group
        5. Ignores the EC2 if it has a duplicate Name tag in the Deployment Group. Also if its part of an Auto Scaling Group
        6. Once added, it looks up the last successful deployment from AWS CodeDeploy
        7. It creates a new deployment based on the artifacts from the prior deployment
        8. Returns "Done"
    :param event: Input json from SNS
    :param context: Not used, but required for Lambda function
    :return: "Done"
    :exception: Catch CustomException only
"""

def lambda_handler(event, context):
    print("Received event: " + json.dumps(event, indent=2))
    instance_id=event['detail']['instance-id']
    try:
        spotid=detect_spot(ec2client,instance_id)
        if spotid:
            tags=get_tags_from_spot_request(ec2client,instance_id,spotid)
            if ("aws:autoscaling:groupName") in tags:
                raise CustomException("EC2 is part of autoscaling group...Ignoring")
            instancetags=mktags(tags)
            createtags(ec2client,instance_id,instancetags)
        else:
            tags=get_instance_info(ec2client,instance_id)
            if ('aws:autoscaling:groupName') in tags:
                raise CustomException("EC2 is part of autoscaling group...Ignoring")
        time.sleep(60)
        name=tags.get('Name')
        codedeploygroup=tags.get('CodeDeployDeploymentGroup')
        appname=tags.get('CodeDeployApplication')
        depresponse=deployment_group_tag(appname,codedeploygroup)
        ec2TagFilters = depresponse['deploymentGroupInfo']['ec2TagFilters']
        if name in str(ec2TagFilters):
            raise CustomException("EC2 has exact name tag as existing EC2's in deployment group..ignoring...")
        for i in range(len(ec2TagFilters)):
            ec2TagFilters.append({
            'Key': 'Name',
            'Value': name,
            'Type': 'KEY_AND_VALUE'})
        update_response = deployment_group_update(appname, codedeploygroup, ec2TagFilters)
        deploymentId =depresponse['deploymentGroupInfo']['lastSuccessfulDeployment']['deploymentId']
        print ("DepId is" +deploymentId)
        depIdResponse=get_dep(deploymentId)
        bucket= depIdResponse['s3Location']['bucket']
        key= depIdResponse['s3Location']['key']
        syncresp=deploy_now(appname,codedeploygroup,bucket,key)
        print (syncresp)
        return 'Done'
    except CustomException as ce:
        print(ce)
        return 'Done'
        
        

def createtags(ec2client,instance_id,instancetags):
    ec2client.create_tags(
        Resources = [instance_id],
        Tags= instancetags
       )

def detect_spot(ec2client, instance_id):

    response = ec2client.describe_instances(
        InstanceIds=[
        instance_id,
    ]
        )
    spotid = "";
    #Getting hostname for instance-id
    for reservation in response["Reservations"]:
        for instance in reservation["Instances"]:
            if instance.get("SpotInstanceRequestId") :
                spotid=instance["SpotInstanceRequestId"]
    return spotid;

class CustomException(Exception):
    """Raise for my specific kind of exception"""

def get_instance_info(ec2client, instance_id):

    response = ec2client.describe_tags(
            Filters = [

                {
                    'Name': 'resource-id',
                    'Values': [
                        instance_id,
                    ]
                },

            ]
        )
    tagdict = {};
    for j in range(len(response['Tags'])):
        tagdict[response['Tags'][j]['Key']] = response['Tags'][j]['Value']

    return tagdict;

def deployment_group_tag(appname,codedeploygroup):
    response = client.get_deployment_group(
            applicationName = appname,
            deploymentGroupName = codedeploygroup
        )
    return response;


def deployment_group_update(appname, codedeploygroup, ec2TagFilters):
    response = client.update_deployment_group(
            applicationName = appname,
            currentDeploymentGroupName = codedeploygroup,
            ec2TagFilters = ec2TagFilters,
            serviceRoleArn = codedeployrole
            )
    return response

def get_dep(deploymentId):
    response=client.get_deployment(deploymentId=deploymentId)
    return response['deploymentInfo']['revision']

def deploy_now(appname,codedeploygroup,bucket,key):
    response = client.create_deployment(
    applicationName=appname,
    deploymentGroupName=codedeploygroup,
    deploymentConfigName='CodeDeployDefault.OneAtATime',
    description='Test',
    ignoreApplicationStopFailures=True,
    updateOutdatedInstancesOnly=True,
    fileExistsBehavior='OVERWRITE')

    return response

def get_tags_from_spot_request(ec2client,instance_id,spot_instance_request_id):
    response=ec2client.describe_tags(
            Filters = [

                {
                    'Name': 'resource-id',
                    'Values': [
                        spot_instance_request_id,
                    ]
                },

            ]
        )
    tagdict = {};
    for j in range(len(response['Tags'])):
        tagdict[response['Tags'][j]['Key']] = response['Tags'][j]['Value']
    return tagdict

def mktags(taglst):
        tags = []
        for t in taglst:
            tags.append({'Key': t, 'Value': taglst[t]})
        return tags

