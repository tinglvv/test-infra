#!/bin/bash -e
exec > >(tee /var/log/user-data.log | logger -t user-data -s 2>/dev/console) 2>&1

# Install AWS CLI
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y awscli jq

# Install runner
cd /home/ubuntu
mkdir actions-runner && cd actions-runner

aws s3 cp ${s3_location_runner_distribution} actions-runner.tar.gz
tar xzf ./actions-runner.tar.gz
rm -rf actions-runner.tar.gz

INSTANCE_ID=$(wget -q -O - http://169.254.169.254/latest/meta-data/instance-id)
REGION=$(curl -s 169.254.169.254/latest/dynamic/instance-identity/document | jq -r .region)

echo wait for configuration
while [[ $(aws ssm get-parameters --names ${environment}-$INSTANCE_ID --with-decryption --region $REGION | jq -r ".Parameters | .[0] | .Value") == null ]]; do
    echo Waiting for configuration ...
    sleep 1
done
CONFIG=$(aws ssm get-parameters --names ${environment}-$INSTANCE_ID --with-decryption --region $REGION | jq -r ".Parameters | .[0] | .Value")
aws ssm delete-parameter --name ${environment}-$INSTANCE_ID --region $REGION

export RUNNER_ALLOW_RUNASROOT=1

sudo -u ubuntu mkdir /home/ubuntu/work

./bin/installdependencies.sh
./config.sh --unattended --name $INSTANCE_ID --work "/home/ubuntu/work" $CONFIG

chown -R ubuntu:ubuntu .
./svc.sh install ubuntu

./svc.sh start
