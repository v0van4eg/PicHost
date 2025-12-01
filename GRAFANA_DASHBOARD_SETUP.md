# Grafana Dashboard Setup Guide

## Overview
This guide provides instructions for importing and using the PiHosting Application Dashboard in Grafana.

## Dashboard Features
- **Application Metrics**: Displays key metrics from the PiHosting application
- **Disk Usage Monitoring**: Shows disk usage statistics for different paths
- **HTTP Request Metrics**: Tracks request rates, status codes, and response times
- **Content Statistics**: Shows album, article, and file counts
- **System Health**: Monitors database size and application uptime

## Importing the Dashboard

### Method 1: JSON File Import
1. Open Grafana in your browser
2. Navigate to the "Dashboards" section
3. Click "New" and then "Import"
4. Upload either of these files:
   - `/workspace/grafana_dashboard.json`
   - `/workspace/grafana_dashboard_fixed.json`
5. The dashboard will be imported with all panels configured

### Method 2: JSON Content Import
1. Copy the contents of either JSON file
2. In Grafana, go to "Dashboards" → "New" → "Import"
3. Paste the JSON content in the text area
4. Click "Load" and then "Import"

## Required Data Source
Make sure you have a Prometheus data source configured in Grafana that can access your PiHosting application metrics at the `/metrics` endpoint.

## Panel Descriptions

### Content Metrics
- **Total Albums**: Shows the current number of albums in the system
- **Total Articles**: Shows the current number of articles in the system  
- **Total Files**: Shows the total number of files stored
- **Application Uptime**: Shows how long the application has been running

### Storage Metrics
- **Disk Usage Percentage**: Gauge showing percentage of disk used across different paths
- **Disk Space Usage**: Time series showing total, used, and free disk space

### HTTP Metrics
- **HTTP Request Rate**: Shows requests per second by HTTP method
- **HTTP Status Codes**: Shows distribution of HTTP response status codes
- **HTTP Request Duration**: Shows 95th percentile response times by method
- **Active Connections**: Shows current number of active connections

### System Metrics
- **Database Size**: Shows the size of the application database
- **Content Growth Over Time**: Shows trends in content creation over time

## Troubleshooting

### If Panels Show No Data
- Verify that Prometheus is scraping metrics from your application
- Check that the data source in Grafana is properly configured
- Confirm that the metric names in the dashboard match those exposed by the application
- Ensure the application is running and the `/metrics` endpoint is accessible

### Common Issues
- Make sure the Prometheus data source is selected when importing the dashboard
- Check that the application is exposing metrics in the expected format
- Verify that Grafana has network access to the application's metrics endpoint

## Schema Version
The dashboard is formatted for Grafana schema version 38, compatible with recent versions of Grafana.