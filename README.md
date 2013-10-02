# kibana_utils
--------------

Fabric-based utilities for working with Kibana (backups, etc)

Primarily, this is used to back up Kibana dashboards that are stored in ElasticSearch to S3.  This provides tasks to interact with ElasticSearch and S3, i.e. backing up data to S3 and restoring from an S3 dump into ElasticSearch.

## Requirements

These pip packages are required:

* `pip install requests`
* `pip install boto`
* `pip install fabric`

## Configuration

Boto is used to connect to S3.  Specify your AWS creds and buckey with environment variables.

```
export AWS_SECRET_ACCESS_KEY=asdf
export AWS_ACCESS_KEY_ID=candycane
export KIBANA_BUCKET=my-bucket
export KIBANA_PREFIX=kibana-backups
```

By default, this looks for ElasticSearch on localhost:9200.  This can be configured with the following environment variables:

```
export ELASTIC_SEARCH_HOST=127.0.02
export ELASTIC_SEARCH_PORT=9292
```



## Usage (standard fabric)

List tasks

`fab -f fabfile.py -l`

Run a task

`fab -f fabfile.py backup`

Run a parameterized task

`fab -f fabfile.py restore_dashboards:some_backup.json`
