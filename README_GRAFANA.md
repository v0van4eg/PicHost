# Grafana Dashboard for Application Metrics

This dashboard provides comprehensive monitoring for your Python application with the following key metrics:

## Dashboard Features

- **Application Uptime**: Shows how long the application has been running
- **Memory Usage**: Monitors both resident and virtual memory consumption
- **Disk Usage**: Tracks disk space usage for the application's image storage
- **Content Statistics**: Shows counts of albums, articles, and files in the system
- **Database Metrics**: Monitors database size
- **Python Runtime Metrics**: Includes garbage collection statistics
- **System Metrics**: Process CPU usage, file descriptors, and more

## Panel Layout

The dashboard is organized into multiple sections:

1. **Overview Stats** (Top row):
   - Application uptime
   - Active connections
   - Python version information
   - CPU usage
   - Process memory metrics

2. **Content Statistics** (Second row):
   - Album count
   - Article count
   - File count
   - Database size
   - Disk usage metrics

3. **Time Series Graphs** (Remaining panels):
   - Memory usage over time
   - Disk usage trends
   - Content growth patterns
   - Database size changes
   - Python garbage collection metrics
   - System file descriptor usage

## How to Import

1. In Grafana, go to **Dashboards** → **Import**
2. Choose the `application_dashboard.json` file
3. Select your Prometheus data source
4. Click **Import**

## Prometheus Metrics Used

The dashboard uses these application metrics:

- `application_uptime_seconds` - Application uptime
- `active_connections` - Active connections count
- `album_count`, `article_count`, `file_count` - Content statistics
- `database_size_bytes` - Database size
- `disk_usage_bytes_total`, `disk_usage_bytes_free`, `disk_usage_bytes_used` - Disk usage
- `process_resident_memory_bytes`, `process_virtual_memory_bytes` - Memory metrics
- `process_cpu_seconds_total` - CPU usage
- `process_open_fds`, `process_max_fds` - File descriptor metrics
- `python_gc_collections_total`, `python_gc_objects_collected_total` - Garbage collection metrics

## Configuration

The dashboard refreshes automatically every 5 seconds and shows data from the last 15 minutes by default. You can adjust these settings in the dashboard configuration.