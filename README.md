# Elasticsearch Backup Container

This container enables full backups of either a specific index, or an entire server, to a specified location. Server backups include templates, plus the regular index backup data.

## Environment variables

The following environment variables can be used to configure the container:

|   Property    |                     Description                      | Required |      Example       |
| ------------- | ---------------------------------------------------- | -------- | ------------------ |
| HOST          | Path to elasticsearch server.                        | True     | http://server:9200 |
| OUTPUT        | Directory to place backup in                         | True     | /data/backup       |
| INDEX         | Index to backup. Will backup server if not provided. | False    | `records`          |
| CRON_SCHEDULE | Schedule to use for backup. Defaults to daily at 1am | False    | `0 1 * * *`        |

When restoring, you can pass in the following parameters:

| Parameters  |                      Description                      | Required |      Example       |
| ----------- | ----------------------------------------------------- | -------- | ------------------ |
| --host      | Path to elasticsearch server.                         | True     | http://server:9200 |
| --index     | Index to restore. Will restore server if not provided | False    | data-index         |
| --force     | Force deletion of existing indices during restore     | False    |                    |
| --path      | Path to directory with server or index backup         | True     | /data/backup       |
| --replicas  | Set the number of replicas for index                  | False    | 2                  |
| --max_items | Max number of items to submit per batch               | False    | 100                | 

## Usage

To back up a server:

```bash
docker run es-backup:latest -e HOST=http://server:9200 -e OUTPUT=/data/backup -d --name es-backup
```

To restore:
```bash
docker run es-backup:latest /apps/scripts/restore.py --host http://new-server:9200 --path /data/backup/server_backup --force
```
