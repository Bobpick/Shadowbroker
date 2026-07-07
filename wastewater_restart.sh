docker exec shadowbroker-backend sh -c 'echo "{\"cursor\":0,\"unfetched_cursor\":0,\"no_data_retry_cursor\":0}" > /app/data/wastewater_fetch_state.json'
docker restart shadowbroker-backend
