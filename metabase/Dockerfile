# Use the official Metabase Docker image as a base
FROM metabase/metabase:latest

# Create a directory inside the container to hold your SQLite file
RUN mkdir -p /metabase_data

# Declare a volume for the SQLite file directory
VOLUME ["/metabase_data"]

# Expose port 3000 (Metabase default port)
EXPOSE 3000
