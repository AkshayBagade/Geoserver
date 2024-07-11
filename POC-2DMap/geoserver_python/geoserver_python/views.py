from rest_framework import status
from rest_framework.response import Response
from .models import GISPointModel,GISContour,GISDelunaryTriangleModel
from rest_framework.decorators import api_view
import json
import pandas as pd
import numpy as np
from requests.auth import HTTPBasicAuth
from geoserver.catalog import Catalog
from scipy.spatial import Delaunay
from shapely.geometry import Polygon as poly
from django.contrib.gis.geos import Polygon,Point,LineString
import math
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import requests

# GeoServer details
GEOSERVER_URL = "http://geoserver:8080/geoserver/rest/"
USERNAME = "admin"
PASSWORD_GEOSERVER = "geoserver"

# Django model information
WORKSPACE = "Test"
DATASTORE_NAME = "test123"
DATABASE_NAME = "postgres"
DATABASE_USER = "postgres"
DATABASE_PASSWORD = "Maxval@123"
SCHEMA = "public"
MODEL_NAME = "GISPointModel"
PILE_INFO_TABLE = "geoserver_python_gispointmodel"
PILE_TRIANGULAR_TABLE = "geoserver_python_gisdelunarytrianglemodel"
PILE_CONTOUR_TABLE = "geoserver_python_giscontour"
PILE_CONTOUR_GEO_TIFF_LAYER = "geoserver_python_pile_tiff_layer"

# GeoServer REST API endpoint URLs
# GEOSERVER_URL = 'http://localhost:8080/geoserver/rest'
# WORKSPACE = 'Test'
# DATASTORE_NAME = 'test123'
LAYER_NAME = 'point'

# GeoServer authentication credentials
GEOSERVER_USERNAME = 'admin'
GEOSERVER_PASSWORD = 'geoserver'


# Extend the Catalog class
class ExtendedCatalog(Catalog):
    def enable_services_for_workspace(self, workspace_name):
        services = ['wms', 'wfs', 'wcs']
        for service in services:
            url = f"{self.service_url}/services/{service}/workspaces/{workspace_name}/settings"

            # Payload to enable the service
            payload = {
                service: {
                    "id": f"{service.upper()}_{workspace_name}",
                    "enabled": True,
                    "name": f"{service.upper()}_{workspace_name}",
                    "workspace": {"name": workspace_name},
                    "maxConnections": 10,
                    "maxRenderingTime": 0,
                    "maxRenderingErrors": 0,
                    "verbose": True,
                    "interpolation": "Nearest",
                    "metadata": {},
                    "serviceLevel": "BASIC"
                }
            }

            # Send PUT request to update service settings for the workspace
            response = requests.put(url, json=payload, auth=HTTPBasicAuth(self.username, self.password),
                                    headers={"Content-Type": "application/json"})

            if response.status_code in [200, 201]:
                print(f"{service.upper()} service enabled for workspace '{workspace_name}'.")
            else:
                print(
                    f"Failed to enable {service.upper()} service for workspace '{workspace_name}'. Status code: {response.status_code}, Response: {response.text}")

import concurrent.futures
import time
from osgeo import gdal, osr
import os
from .tasks import my_task
@api_view(['POST'])
# Main function to handle the file upload and parallel processing
def upload_points_v1(request):
    file = request.FILES.get('file')
    if not file:
        return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        # Process file in batches
        # Initialize WebSocket channel layer
        channel_layer = get_channel_layer()
        channel_name = 'progress_group'
        GISPointModel.objects.all().delete()
        GISDelunaryTriangleModel.objects.all().delete()
        GISContour.objects.all().delete()

        batch_size = 1000 # Adjust batch size as needed
        points_data = []
        pile_data = []
        file = pd.read_json(file)
        total_lines = len(file['Trackers'])
        processed_lines = 0

        with concurrent.futures.ProcessPoolExecutor() as executor:
            futures = []
            for line in file['Trackers']:
                try:
                    points_data.append(line)
                    pile_data.append(line['piles'])
                except json.JSONDecodeError:
                    pass

                if len(points_data) >= batch_size:
                    # Submit tasks for parallel processing
                    futures.append(executor.submit(process_points, points_data.copy()))
                    futures.append(executor.submit(process_polygons, pile_data.copy()))
                    points_data = []
                    pile_data = []

                # Update progress
                processed_lines += 1
                progress = int((processed_lines / total_lines) * 50)  # Scale to 0-50%
                try:
                    async_to_sync(channel_layer.group_send)(
                        channel_name,
                        {
                            'type': 'send.progress',
                            'progress': progress
                        }
                    )
                except Exception as e:
                    print(e)

            # Process remaining points
            if points_data:
                futures.append(executor.submit(process_points, points_data))
                futures.append(executor.submit(process_polygons, pile_data))

            # Collect results from futures
            points_to_create = []
            triangle_to_create = []

            total_futures = len(futures)
            completed_futures = 0
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if isinstance(result, list) and len(result) > 0:
                    if isinstance(result[0], GISPointModel):
                        points_to_create.extend(result)
                    elif isinstance(result[0], GISDelunaryTriangleModel):
                        triangle_to_create.extend(result)

                # Update progress for the second part
                completed_futures += 1
                progress = 50 + int((completed_futures / total_futures) * 50)  # Scale to 50-100%
                try:
                    async_to_sync(channel_layer.group_send)(
                        channel_name,
                        {
                            'type': 'send.progress',
                            'progress': progress
                        }
                    )
                except Exception as e:
                    print(e)
            #
            # # Bulk create points and triangles
            GISPointModel.objects.bulk_create(points_to_create)
            GISDelunaryTriangleModel.objects.bulk_create(triangle_to_create)

        # create_contour_layer()
        create_geo_tiff()
        return Response({"status": "File processed successfully"}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def concurrency_logic(file):
    batch_size = 1000
    points_data = []
    pile_data =  []
    channel_layer = get_channel_layer()
    channel_name = 'progress_group'

    for line in file:
        for data in line:
            try:
                points_data.append(data)
                pile_data.append(data['piles'])
            except json.JSONDecodeError:
                pass

        if len(points_data) >= batch_size:
            process_points(points_data.copy())
            process_polygons(pile_data.copy())

            points_data = []
            pile_data = []

        # Process remaining points
        if points_data:
            process_points(points_data.copy())
            process_polygons(pile_data.copy())


        progress = 2  # Scale to 0-50%
        try:
            async_to_sync(channel_layer.group_send)(
                channel_name,
                {
                    'type': 'send.progress',
                    'progress': progress
                }
            )
        except Exception as e:
            print(e)

@api_view(['POST'])
def upload_points_task(request):
    file = request.FILES.get('file')
    if not file:
        return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        # Process file in batches
        # Initialize WebSocket channel layer
        channel_layer = get_channel_layer()
        channel_name = 'progress_group'
        GISPointModel.objects.all().delete()
        GISDelunaryTriangleModel.objects.all().delete()
        GISContour.objects.all().delete()

        batch_size = 1000  # Adjust batch size as needed
        points_data = []
        pile_data = []
        file = pd.read_json(file)
        total_lines = len(file['Trackers'])
        batches = total_lines / batch_size
        batches = math.ceil(batches)
        w = 0
        batch_list = []
        for i in range(0, batches):
            temp = []
            data = file['Trackers'][w: w + batch_size]
            temp.append(data.tolist())
            batch_list.append(temp)
            w = w + batch_size

        with concurrent.futures.ThreadPoolExecutor() as executor:
            # Submit tasks asynchronously
            for batch in batch_list:
                executor.submit(concurrency_logic, batch)


        return Response({"status": "File processed successfully"}, status=status.HTTP_200_OK)


    #     # create_contour_layer()
    #     create_geo_tiff()
    #     return Response({"status": "File processed successfully"}, status=status.HTTP_200_OK)
    #
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

from django.db import transaction
# Helper function to process polygons using DataFrame
def process_polygons(pile_data):
    print("polygon_started")
    polygon = delunary_calculate(pile_data)
    df = pd.DataFrame(polygon)
    df['name'] = 'P1' + df.index.astype(str)
    df['geom'] = df['polygon_data']
    df['grading'] = df['grading'].apply(lambda x: float("{:.2f}".format(x)))

    triangle_to_create = [
        GISDelunaryTriangleModel(name=row['name'], geom=row['geom'], grading=row['grading'])
        for _, row in df.iterrows()
    ]
    GISDelunaryTriangleModel.objects.bulk_create(triangle_to_create)
    print("polygon_ended")
    return triangle_to_create

from pyproj import CRS
import geopandas as gpd
def create_shape_file(points_data):
    from shapely.geometry import Point
    pile_data = []
    for point_data in points_data:
        for pile in point_data['piles']:
            pile_data.append({
                'name': 'P1',
                'longitude': pile['Position']['lon'],
                'latitude': pile['Position']['lat'],
                'grading': float(pile['Solution']['Grading']),
                'bottom_of_pile': float(pile['Solution']['Bottom'])
            })

    # Convert latitude and longitude to Points
    geometry = [Point(lon, lat) for lon, lat in zip(
        [d["longitude"] for d in pile_data],
        [d["latitude"] for d in pile_data]
    )]

    # Define the coordinate reference system (CRS)
    crs = CRS.from_epsg(4326)  # WGS84 (standard geographic coordinate system)

    # Create a GeoDataFrame
    gdf = gpd.GeoDataFrame(pile_data, geometry=geometry, crs=crs)

    # Save the GeoDataFrame as a shapefile
    output_shapefile = 'points.shp'
    gdf.to_file(output_shapefile)


# Helper function to process points using DataFrame
def process_points(points_data):
    print("point_started")
    pile_data = []
    for point_data in points_data:
        for pile in point_data['piles']:
            pile_data.append({
                'name': 'P1',
                'longitude': pile['Position']['lon'],
                'latitude': pile['Position']['lat'],
                'grading': float(pile['Solution']['Grading']),
                'bottom_of_pile':float(pile['Solution']['Bottom'])
            })

    df = pd.DataFrame(pile_data)
    df['name'] += df.index.astype(str)
    df['geom'] = df.apply(lambda row: Point(row['longitude'], row['latitude']), axis=1)

    points_to_create = [
        GISPointModel(name=row['name'], geom=row['geom'], grading=row['grading'],bottom_of_pile=row['bottom_of_pile'])
        for _, row in df.iterrows()
    ]
    GISPointModel.objects.bulk_create(points_to_create)
    print("point_ended")
    return points_to_create

@api_view(['POST'])
def upload_points(request):
    file = request.FILES.get('file')
    if not file:
        return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        # Process file in batches
        GISPointModel.objects.all().delete()
        GISDelunaryTriangleModel.objects.all.delete()
        GISContour.objects.all.delete()
        batch_size = 1000  # Adjust batch size as needed
        points_data = []
        pile_data = []
        file =  pd.read_json(file)
        # trackers = file['Trackers'][:10]
        for line in file['Trackers']:
            try:
                points_data.append(line)
                pile_data.append(line['piles'])
            except json.JSONDecodeError:
                pass

            if len(points_data) >= batch_size:
                process_batch(points_data)
                points_data = []

        # Process remaining points
        if points_data:
            process_batch(points_data,pile_data)

        create_contour_layer()

        return Response({"message": "Data uploaded successfully"}, status=status.HTTP_201_CREATED)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def process_batch(points_data,pile_data):
    points_to_create = []
    triangle_to_create = []
    index = 0
    polygon = delunary_calculate(pile_data)
    for obj in polygon:
        name = 'P1' + str(index)
        point_model = GISDelunaryTriangleModel(name=name, geom=obj['polygon_data'], grading=float("{:.2f}".format(float(obj['grading']))))
        triangle_to_create.append(point_model)
        index+=1

    for point_data in points_data:
        for pile in point_data['piles']:
            name = 'P1' + str(index)
            longitude = pile['Position']['lon']
            latitude = pile['Position']['lat']
            grading = float(pile['Solution']['Grading'])
            geom = Point(longitude, latitude)  # Creating a Point geometry
            print('adding')
            point_model = GISPointModel(name=name, geom=geom,grading=grading)
            points_to_create.append(point_model)
            index+=1

    print('bluk adding')
    GISPointModel.objects.bulk_create(points_to_create)
    GISDelunaryTriangleModel.objects.bulk_create(points_to_create)


def delunary_calculate(points_data):
    easting_northing = [(item['Position_utm']['Easting'], item['Position_utm']['Northing'],item['Position']['lat'],item['Position']['lon'],item['Solution']['Grading']) for data in points_data for item in data]
    df = pd.DataFrame(easting_northing, columns=['Easting', 'Northing','lat','lon','Grading'])
    ref_points = df[['Easting', 'Northing']]
    triangulation = Delaunay(ref_points)
    ref_points_utm = df[['Easting', 'Northing']].values
    all_triangle_areas = 0.5 * np.abs(
        np.cross(
            ref_points.values[triangulation.simplices[:, 1]] - ref_points.values[triangulation.simplices[:, 0]],
            ref_points.values[triangulation.simplices[:, 2]] - ref_points.values[triangulation.simplices[:, 0]]))
    most_common_area = np.median(all_triangle_areas)

    filtered_simplices = [triangle for triangle in triangulation.simplices if
                          poly(ref_points.values[triangle]).area <= math.ceil(
                              most_common_area * 1.3)]

    filter_df = pd.DataFrame(filtered_simplices)

    flat_simplices = [point for simplex in filtered_simplices for point in simplex]
    # flat_Polygon = [Polygon(ref_points.values[triangle]) for triangle in filtered_simplices]
    flat_Polygon = []
    # Use this plot if you want to see the FILTERED SIMPLICES plot
    # plt.triplot(ref_points["Easting"], ref_points["Northing"], filtered_simplices, color='r')
    # plt.xlabel('x')
    # plt.ylabel('y')
    # plt.legend()
    # plt.show()
    #
    # # Use this plot if you want to see the FILTERED SIMPLICES plot
    # plt.triplot(df["lon"], df["lat"], filtered_simplices, color='y')
    # plt.xlabel('x')
    # plt.ylabel('y')
    # plt.legend()
    # plt.show()

    # for triangle in filtered_simplices:
    #     # Get the points forming the triangle
    #     triangle_points = df[['lon', 'lat']].iloc[triangle]
    #     # Close the ring by adding the first point at the end
    #     triangle_points = np.vstack([triangle_points, triangle_points.iloc[0]])
    #     grading_val = sum(df[['Grading']].iloc[triangle].values) / 3
    #     # Create a Polygon from the points
    #     polygon = Polygon(triangle_points.tolist())
    #     flat_Polygon.append({'polygon_data':polygon,'grading':grading_val})

    # Define a function to calculate the grading value for a triangle
    def calculate_grading(triangle, df):
        return df['Grading'].iloc[triangle].mean()

    # Define a function to create a polygon from triangle points
    def create_polygon(triangle_points):
        # coordinates = list(zip(triangle_points['lon'], triangle_points['lat']))
        # coordinates = [list(coord) for coord in coordinates if not np.isnan(coord[0])]
        return Polygon(triangle_points.tolist())

    # Optimize the loop
    flat_Polygon = [{'polygon_data': create_polygon(
        np.vstack([df[['lon', 'lat']].iloc[triangle], df[['lon', 'lat']].iloc[triangle[0]]])),
                     'grading': calculate_grading(triangle, df)}
                    for triangle in filtered_simplices]


    return flat_Polygon

def extract_lat_lon(geom_string):
    # Regular expression pattern to match numeric values
    pattern = r'[-+]?\d*\.\d+|\d+'

    # Find all numeric values in the string
    matches = re.findall(pattern, geom_string)

    print(matches)

    # Extract latitude and longitude from the matches
    latitude = float(matches[1])  # Index 1 corresponds to latitude
    longitude = float(matches[2])  # Index 0 corresponds to longitude

    return matches

@api_view(['GET'])
def publish_layer_geoserver(request):
    create_data_store()
    wmnsurl = publish_layer()
    return Response({'message':'Successfully Publish Point','url':'http://localhost:8080/geoserver/Test/wms'})


def create_json_data(spatial_data):
    geojson_data = {
        'type': 'FeatureCollection',
        'features': [
            {
                'type': 'Feature',
                'geometry': {
                    'type': 'Point',
                    'coordinates': [extract_lat_lon(str(obj.geom))[1], extract_lat_lon(str(obj.geom))[2]],
                },
                'properties': {
                    'name': obj.name,
                    # Add any additional properties here
                }
            }
            for obj in spatial_data
        ]
    }

    return geojson_data

def create_workspace(catalog):
    existing_workspace = catalog.get_workspace(WORKSPACE)
    if existing_workspace:
        print(f"Workspace '{WORKSPACE}' already exists.")
    else:
        # Create a new workspace
        new_workspace = catalog.create_workspace(WORKSPACE)
        # Enable settings and services for the workspace
        catalog.set_default_workspace(WORKSPACE)
        # Initialize extended GeoServer catalog
        # cat = ExtendedCatalog(GEOSERVER_URL, USERNAME, PASSWORD_GEOSERVER)
        set_default(GEOSERVER_URL, USERNAME, PASSWORD_GEOSERVER, WORKSPACE)
        # enable_services(GEOSERVER_URL, USERNAME, PASSWORD_GEOSERVER, WORKSPACE,catalog,new_workspace)
        if new_workspace:
            print(f"Workspace '{WORKSPACE}' created successfully.")
        else:
            print(f"Failed to create workspace '{WORKSPACE}'.")


# Function to enable settings and services, and set the workspace as default
def set_default(geoserver_url, username, password, workspace_name):
    headers = {
        'Content-Type': 'application/json'
    }

    # Set the workspace as default
    default_payload = {
        "workspace": {
            "name": workspace_name
        }
    }

    default_url = f"{geoserver_url}/workspaces/default.json"
    default_response = requests.put(default_url, headers=headers, auth=(username, password),
                                    data=json.dumps(default_payload))

    if default_response.status_code == 200:
        print(f"Workspace '{workspace_name}' set as default successfully.")
    else:
        print(
            f"Failed to set workspace '{workspace_name}' as default. Status code: {default_response.status_code}, Response: {default_response.text}")

# Function to enable WMS and WFS services for the workspace
def enable_services(geoserver_url, username, password, workspace_name,cat,workspace):
    # Enable WMS
    wms_settings = cat.get_service('wms')
    if not wms_settings.enabled:
        wms_settings.enabled = True
        cat.save(wms_settings)
        print("WMS service enabled.")

    # Enable WFS
    wfs_settings = cat.get_service('wfs')
    if not wfs_settings.enabled:
        wfs_settings.enabled = True
        cat.save(wfs_settings)
        print("WFS service enabled.")

    # Enable WCS
    wcs_settings = cat.get_service('wcs')
    if not wcs_settings.enabled:
        wcs_settings.enabled = True
        cat.save(wcs_settings)
        print("WCS service enabled.")

    # Confirming services are enabled
    print(f"WMS enabled: {wms_settings.enabled}")
    print(f"WFS enabled: {wfs_settings.enabled}")
    print(f"WCS enabled: {wcs_settings.enabled}")

    # Set content information for the workspace (optional)
    workspace.metadata['title'] = 'My Workspace Title'
    workspace.metadata['abstract'] = 'This is an abstract for my workspace.'
    cat.save(workspace)
    print(f"Workspace metadata updated for '{workspace_name}'.")

    headers = {
        'Content-Type': 'application/json'
    }

    # WMS service settings payload
    wms_payload = {
        "wms": {
            "id": f"{workspace_name}:wms",
            "enabled": True,
            "name": workspace_name,
            "title": f"{workspace_name} WMS",
            "abstract": f"WMS for {workspace_name}",
            "workspace": {"name": workspace_name}
        }
    }

    # WFS service settings payload
    wfs_payload = {
        "wfs": {
            "id": f"{workspace_name}:wfs",
            "enabled": True,
            "name": workspace_name,
            "title": f"{workspace_name} WFS",
            "abstract": f"WFS for {workspace_name}",
            "workspace": {"name": workspace_name}
        }
    }

    # Enable WMS service
    wms_url = f"{geoserver_url}/services/wms/workspaces/{workspace_name}/settings.json"
    wms_response = requests.put(wms_url, headers=headers, auth=(username, password), data=json.dumps(wms_payload))

    if wms_response.status_code in [200, 201]:
        print(f"WMS service for workspace '{workspace_name}' enabled successfully.")
    else:
        print(f"Failed to enable WMS service for workspace '{workspace_name}'. Status code: {wms_response.status_code}, Response: {wms_response.text}")

    # Enable WFS service
    wfs_url = f"{geoserver_url}services/wfs/workspaces/{workspace_name}/settings.json"
    wfs_response = requests.put(wfs_url, headers=headers, auth=(username, password), data=json.dumps(wfs_payload))

    if wfs_response.status_code in [200, 201]:
        print(f"WFS service for workspace '{workspace_name}' enabled successfully.")
    else:
        print(f"Failed to enable WFS service for workspace '{workspace_name}'. Status code: {wfs_response.status_code}, Response: {wfs_response.text}")


def create_data_store():
    DATASTORE_NAME = 'test_123'
    WORKSPACE = 'Test'
    catalog = Catalog(GEOSERVER_URL, username=USERNAME, password=PASSWORD_GEOSERVER)
    create_workspace(catalog)
    workspace = catalog.get_workspace(WORKSPACE)

    # Get the data store
    data_store = None
    try:
        data_store = catalog.get_store(DATASTORE_NAME, workspace)
    except:
        pass

    if data_store is None:
        data_store = catalog.create_datastore(DATASTORE_NAME, workspace)
        data_store.connection_parameters.update(host="db", port="5432", database=DATABASE_NAME,
                                                user=DATABASE_USER, passwd=DATABASE_PASSWORD, dbtype="postgis",
                                                schema=SCHEMA)
        catalog.save(data_store)

        print('Data store created successfully')
    else:
        # Delete the data store
        catalog.delete(data_store, purge=True,recurse=True)
        print(f"Data store '{DATASTORE_NAME}' deleted successfully.")
        data_store = catalog.create_datastore(DATASTORE_NAME, workspace)
        data_store.connection_parameters.update(host="db", port="5432", database=DATABASE_NAME,
                                                user=DATABASE_USER, passwd=DATABASE_PASSWORD, dbtype="postgis",
                                                schema=SCHEMA)
        catalog.save(data_store)

        print('Data store created successfully')

def get_features():
    # Fetch instances from your Django model
    gis_point_instances = GISPointModel.objects.all()

    # Create a list to hold features
    features = []

    # Loop through instances and create features
    for instance in gis_point_instances:
        # Get the location coordinates from the GISPointModel instance
        location = instance.geom

        # Create the feature with attributes and location
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [location.x, location.y]  # Assuming location is a Point instance
            },
            "properties": {
                "name": instance.name,
                "description": instance.grading
            }
        }

        # Add the feature to the list
        features.append(feature)

    return features

COLOR_RANGE = ['#FF0000', '#FFFF00', '#00FF00', '#0000FF']
# Publish heatmap layer in GeoServer
def publish_layer():
    WORKSPACE = 'Test'
    catalog = Catalog(GEOSERVER_URL, username=USERNAME, password=PASSWORD_GEOSERVER)
    workspace = catalog.get_workspace(WORKSPACE)

    # Create style for the heatmap
    # style = catalog.create_style('heatmap_style_2', 'sld')
    # style.sld.body = generate_sld_body(COLOR_RANGE)
    # catalog.save(style)
    # style = catalog.get_style('New_heat')
    # catalog.create_style('New_heat', SLD_CONTENT,overwrite=True,workspace=WORKSPACE,style_format="sld10")
    # style = catalog.get_style('New_heat',workspace=WORKSPACE)
    # print('Styled publish')

    # Publish layer with the heatmap style
    DATASTORE_NAME = 'test_123'
    data_store = catalog.get_store(DATASTORE_NAME, workspace)
    print(data_store.resource_url)
    layer = catalog.publish_featuretype(PILE_INFO_TABLE, data_store, native_crs="EPSG:4326", jdbc_virtual_table=PILE_INFO_TABLE)
    # Apply the style to the published layer
    # print('Style-----',style)
    pile_info_layer = catalog.get_layer(PILE_INFO_TABLE)
    # layer.default_style = style

    catalog.publish_featuretype(PILE_TRIANGULAR_TABLE, data_store, native_crs="EPSG:4326", jdbc_virtual_table=PILE_TRIANGULAR_TABLE)
    catalog.publish_featuretype(PILE_CONTOUR_TABLE, data_store, native_crs="EPSG:4326", jdbc_virtual_table=PILE_CONTOUR_TABLE)
    pile_triangle_layer = catalog.get_layer(PILE_TRIANGULAR_TABLE)
    pile_contour_layer = catalog.get_layer(PILE_CONTOUR_TABLE)
    catalog.save(pile_info_layer)
    catalog.save(pile_triangle_layer)
    catalog.save(pile_contour_layer)
    print('Successfully Publish Point')

    publish_geotiff_layer(catalog,workspace)

def calculate_intervals(max_value, interval=10):
    # Calculate the range for grading
    grading_values = list(range(-int(max_value), int(max_value) + interval, interval))
    # Ensure 0 is included
    if 0 not in grading_values:
        grading_values.append(0)
    # Sort and ensure unique values
    grading_values = sorted(set(grading_values))
    return grading_values

@api_view(['POST'])
def update_style_to_layer(request):
    is_contour = True if 'is_contour' in  request.data else False
    is_geoserver_heat_styling = True if 'is_geoserver_heat_styling' in request.data else False
    if is_contour:
        interval = request.data['interval']
        grading_val = list(GISPointModel.objects.values_list('bottom_of_pile', flat=True))
        grading_val = [float(f'{data:.2f}') for data in grading_val]
        min_grading = min(grading_val)
        max_grading = max(grading_val)
        gradings = calculate_intervals(max_grading,interval)
        # cut_range = -max_grading / 5
        # fill_range = max_grading / 5
        # cut_values = calculate_values(cut_range,True)
        # fill_values = calculate_values(fill_range,True)
        # fill_values.reverse()
        # grading = cut_values + [0] + fill_values
        # Update the XML content using str.format()
        # updated_sld_content = SLD_CONTENT_CONTOUR.format(value0=grading[0], value1=grading[1], value2=grading[2],
        #                                                  value3=grading[3], value4=grading[4], value5=grading[5],
        #                                                  value6=grading[6], value7=grading[7], value8=grading[8],
        #                                                  value9=grading[9], value10=grading[10])

        # Create dynamic <ogc:Literal> elements
        ogc_literals = "\n".join([f'<ogc:Literal>{value}</ogc:Literal>' for value in gradings])

        updated_sld_content = SLD_CONTENT_CONTOUR.format(literals=ogc_literals)
    else:
        is_dynamic = request.data['is_dynamic']
        if is_geoserver_heat_styling:
            # Update the XML content using str.format()
            updated_sld_content = SLD_CONTENT_GEOSERVER_STYLING

        elif is_dynamic:
            grading_val = list(GISDelunaryTriangleModel.objects.values_list('grading', flat=True))
            grading_val = [float(f'{data:.2f}') for data in grading_val]
            min_grading = min(grading_val)
            max_grading = max(grading_val)
            cut_range = -max_grading / 5
            fill_range = max_grading / 5
            cut_values = calculate_values(cut_range)
            fill_values = calculate_values( fill_range)
            fill_values.reverse()
            grading = cut_values + [0] +  fill_values
            # Update the XML content using str.format()
            updated_sld_content = SLD_CONTENT_DYNAMIC.format(value0=grading[0], value1=grading[1], value2=grading[2],
                                                           value3=grading[3], value4=grading[4], value5=grading[5],
                                                           value6=grading[6], value7=grading[7], value8=grading[8],
                                                           value9=grading[9], value10=grading[10])
        else:
            grading = [-0.6,-0.45,-0.3,-0.15,-0.05,0.0,0.05,0.15,0.3,0.45,0.6]
            # Update the XML content using str.format()
            updated_sld_content = SLD_CONTENT_FIXED.format(value0=grading[0], value1=grading[1],value2=grading[2],value3=grading[3],value4=grading[4],value5=grading[5],
                                                     value6=grading[6],value7=grading[7],value8=grading[8],value9=grading[9],value10=grading[10])
    catalog = Catalog(GEOSERVER_URL, username=USERNAME, password=PASSWORD_GEOSERVER)
    catalog.create_style('New_heat', updated_sld_content, overwrite=True, workspace=WORKSPACE, style_format="sld10")
    style = catalog.get_style('New_heat', workspace=WORKSPACE)
    if is_contour:
        layer = catalog.get_layer(PILE_CONTOUR_GEO_TIFF_LAYER)
    elif is_geoserver_heat_styling:
        layer = catalog.get_layer(PILE_INFO_TABLE)
    else:
        layer = catalog.get_layer(PILE_TRIANGULAR_TABLE)
    layer.default_style = style
    layer.enabled = True
    catalog.save(layer)
    print('Successfully update style')
    return Response({'message':'Successfully Update style','url':'http://localhost:8080/geoserver/Test/wms'})

def calculate_values(range_val,is_contour=True):
    values = []
    for i in range(5, 0, -1):  # Iterate from 10 to 0
        if is_contour:
            value = int(round((range_val * i), 2))
        else:
            value = round((range_val * i), 2)
        values.append(value)
    return values

# SLD content for the heat map style
SLD_CONTENT_FIXED = """
<sld:StyledLayerDescriptor version="1.{value5}"
    xsi:schemaLocation="http://www.opengis.net/sld StyledLayerDescriptor.xsd"
    xmlns="http://www.opengis.net/sld"
    xmlns:sld="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <sld:NamedLayer>
        <sld:Name>polygon_style</sld:Name>
        <sld:UserStyle>
            <sld:Title>Polygon Style Based on Grading</sld:Title>
            <sld:FeatureTypeStyle>
                <sld:Rule>
                    <sld:Name>{value0}</sld:Name>
                    <sld:Title>{value0}</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsLessThanOrEqualTo>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:Literal>{value0}</ogc:Literal>
                        </ogc:PropertyIsLessThanOrEqualTo>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#BF00FF</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <sld:Name>{value1}</sld:Name>
                    <sld:Title>{value1}</sld:Title>
                     <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>{value0}</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>{value1}</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#3F00FF</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <sld:Name>{value2}</sld:Name>
                    <sld:Title>{value2}</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>{value1}</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>{value2}</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#003FFF</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <sld:Name>{value3}</sld:Name>
                    <sld:Title>{value3}</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>{value2}</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>{value3}</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#00BFFF</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <sld:Name>{value4}</sld:Name>
                    <sld:Title>{value4}</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>{value3}</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>{value4}</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#00FFBF</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <sld:Name>{value5}</sld:Name>
                    <sld:Title>{value5}</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>{value4}</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>{value5}</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#D6D6D6</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>{value5}</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>{value6}</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#D6D6D6</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <sld:Name>{value6}</sld:Name>
                    <sld:Title>{value6}</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>{value6}</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>{value7}</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#3FFF00</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <sld:Name>{value7}</sld:Name>
                    <sld:Title>{value7}</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>{value7}</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>{value8}</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#BFFF00</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                 <sld:Rule>
                    <sld:Name>{value8}</sld:Name>
                    <sld:Title>{value8}</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>{value8}</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>{value9}</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#FFFF00</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <sld:Name>{value9}</sld:Name>
                    <sld:Title>{value9}</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>{value9}</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>{value10}</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#FFBF00</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                 <sld:Rule>
                    <sld:Name>{value10}</sld:Name>
                    <sld:Title>{value10}</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsGreaterThanOrEqualTo>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:Literal>{value10}</ogc:Literal>
                        </ogc:PropertyIsGreaterThanOrEqualTo>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#FF0000</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
            </sld:FeatureTypeStyle>
        </sld:UserStyle>
    </sld:NamedLayer>
</sld:StyledLayerDescriptor>

"""

SLD_CONTENT_DYNAMIC = """
<sld:StyledLayerDescriptor version="1.0"
    xsi:schemaLocation="http://www.opengis.net/sld StyledLayerDescriptor.xsd"
    xmlns="http://www.opengis.net/sld"
    xmlns:sld="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <sld:NamedLayer>
        <sld:Name>polygon_style</sld:Name>
        <sld:UserStyle>
            <sld:Title>Polygon Style Based on Grading</sld:Title>
            <sld:FeatureTypeStyle>
                <sld:Rule>
                    <sld:Name>{value0}</sld:Name>
                    <sld:Title>{value0}</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsLessThanOrEqualTo>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:Literal>{value0}</ogc:Literal>
                        </ogc:PropertyIsLessThanOrEqualTo>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#BF00FF</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <sld:Name>{value1}</sld:Name>
                    <sld:Title>{value1}</sld:Title>
                     <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>{value0}</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>{value1}</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#3F00FF</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <sld:Name>{value2}</sld:Name>
                    <sld:Title>{value2}</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>{value1}</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>{value2}</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#003FFF</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <sld:Name>{value3}</sld:Name>
                    <sld:Title>{value3}</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>{value2}</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>{value3}</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#00BFFF</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <sld:Name>{value4}</sld:Name>
                    <sld:Title>{value4}</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>{value3}</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>{value4}</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#00FFBF</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>{value4}</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>-0.05</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#00FFBF</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <sld:Name>0.0</sld:Name>
                    <sld:Title>0.0</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>-0.05</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>0.0</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#D6D6D6</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>0.0</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>0.05</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#D6D6D6</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <sld:Name>{value6}</sld:Name>
                    <sld:Title>{value6}</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>0.05</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>{value6}</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#3FFF00</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <sld:Name>{value7}</sld:Name>
                    <sld:Title>{value7}</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>{value6}</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>{value7}</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#BFFF00</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <sld:Name>{value8}</sld:Name>
                    <sld:Title>{value8}</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>{value7}</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>{value8}</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#FFFF00</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                 <sld:Rule>
                    <sld:Name>{value9}</sld:Name>
                    <sld:Title>{value9}</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>{value8}</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>{value9}</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#FFBF00</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
                <sld:Rule>
                    <sld:Name>{value10}</sld:Name>
                    <sld:Title>{value10}</sld:Title>
                    <ogc:Filter>
                        <ogc:PropertyIsBetween>
                            <ogc:PropertyName>grading</ogc:PropertyName>
                            <ogc:LowerBoundary>
                                <ogc:Literal>{value9}</ogc:Literal>
                            </ogc:LowerBoundary>
                            <ogc:UpperBoundary>
                                <ogc:Literal>{value10}</ogc:Literal>
                            </ogc:UpperBoundary>
                        </ogc:PropertyIsBetween>
                    </ogc:Filter>
                    <sld:PolygonSymbolizer>
                        <sld:Fill>
                            <sld:CssParameter name="fill">#FF0000</sld:CssParameter> <!-- Green -->
                        </sld:Fill>
                    </sld:PolygonSymbolizer>
                </sld:Rule>
            </sld:FeatureTypeStyle>
        </sld:UserStyle>
    </sld:NamedLayer>
</sld:StyledLayerDescriptor>

"""

SLD_CONTENT_CONTOUR = """

<sld:StyledLayerDescriptor version="1.0"
    xsi:schemaLocation="http://www.opengis.net/sld StyledLayerDescriptor.xsd"
    xmlns="http://www.opengis.net/sld"
    xmlns:sld="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
   <sld:NamedLayer>
     <sld:Name>contour_dem</sld:Name>
      <sld:UserStyle>
        <sld:Title>Contour DEM</sld:Title>
        <sld:Abstract>Extracts contours from DEM</sld:Abstract>
        <sld:FeatureTypeStyle>
          <sld:Transformation>
            <ogc:Function name="ras:Contour">
              <ogc:Function name="parameter">
                <ogc:Literal>data</ogc:Literal>
              </ogc:Function>
              <ogc:Function name="parameter">
                <ogc:Literal>levels</ogc:Literal>
                {literals}
              </ogc:Function>
            </ogc:Function>
          </sld:Transformation>
          <sld:Rule>
            <sld:Name>rule1</sld:Name>
            <sld:Title>Contour Line</sld:Title>
            <sld:LineSymbolizer>
              <sld:Stroke>
                <sld:CssParameter name="stroke">#ADD8E6</sld:CssParameter>
                <sld:CssParameter name="stroke-width">1</sld:CssParameter>
              </sld:Stroke>
            </sld:LineSymbolizer>
            <sld:TextSymbolizer>
              <sld:Label>
                <ogc:PropertyName>value</ogc:PropertyName>
              </sld:Label>
              <sld:Font>
                <sld:CssParameter name="font-family">Arial</sld:CssParameter>
                <sld:CssParameter name="font-style">Normal</sld:CssParameter>
                <sld:CssParameter name="font-size">10</sld:CssParameter>
              </sld:Font>
              <sld:LabelPlacement>
                <sld:LinePlacement/>
              </sld:LabelPlacement>
              <sld:Halo>
                <sld:Radius>
                  <ogc:Literal>2</ogc:Literal>
                </sld:Radius>
                <sld:Fill>
                  <sld:CssParameter name="fill">#FFFFFF</sld:CssParameter>
                  <sld:CssParameter name="fill-opacity">0.6</sld:CssParameter>
                </sld:Fill>
              </sld:Halo>
              <sld:Fill>
                <sld:CssParameter name="fill">#000000</sld:CssParameter>
              </sld:Fill>
              <sld:Priority>2000</sld:Priority>
              <sld:VendorOption name="followLine">true</sld:VendorOption>
              <sld:VendorOption name="repeat">100</sld:VendorOption>
              <sld:VendorOption name="maxDisplacement">50</sld:VendorOption>
              <sld:VendorOption name="maxAngleDelta">30</sld:VendorOption>
            </sld:TextSymbolizer>
          </sld:Rule>
        </sld:FeatureTypeStyle>
      </sld:UserStyle>
    </sld:NamedLayer>
   </sld:StyledLayerDescriptor>
   
"""

SLD_CONTENT_CONTOUR_line_String = """<sld:StyledLayerDescriptor version="1.0"
    xsi:schemaLocation="http://www.opengis.net/sld StyledLayerDescriptor.xsd"
    xmlns="http://www.opengis.net/sld"
    xmlns:sld="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">

  <sld:NamedLayer>
    <sld:Name>contour_lines</sld:Name>
    <sld:UserStyle>
      <sld:Title>Contour Lines</sld:Title>
      <sld:FeatureTypeStyle>
        <sld:Rule>
          <sld:LineSymbolizer>
            <sld:Stroke>
              <sld:CssParameter name="stroke">#000000</sld:CssParameter>
              <sld:CssParameter name="stroke-width">1</sld:CssParameter>
            </sld:Stroke>
          </sld:LineSymbolizer>
          
          <sld:TextSymbolizer>
            <sld:Label>
              <ogc:PropertyName>grading</ogc:PropertyName>
            </sld:Label>
            <sld:Font>
              <sld:CssParameter name="font-family">Arial</sld:CssParameter>
              <sld:CssParameter name="font-size">10</sld:CssParameter>
            </sld:Font>
            <sld:LabelPlacement>
              <sld:PointPlacement>
                <sld:AnchorPoint>
                  <sld:AnchorPointX>0.5</sld:AnchorPointX>
                  <sld:AnchorPointY>0.5</sld:AnchorPointY>
                </sld:AnchorPoint>
              </sld:PointPlacement>
            </sld:LabelPlacement>
            <sld:Halo>
              <sld:Radius>1</sld:Radius>
              <sld:Fill>
                <sld:CssParameter name="fill">#FFFFFF</sld:CssParameter>
              </sld:Fill>
            </sld:Halo>
            <sld:Fill>
              <sld:CssParameter name="fill">#000000</sld:CssParameter>
            </sld:Fill>
          </sld:TextSymbolizer>
        </sld:Rule>
      </sld:FeatureTypeStyle>
    </sld:UserStyle>
  </sld:NamedLayer>
</sld:StyledLayerDescriptor>"""

SLD_CONTENT_GEOSERVER_STYLING = """
<sld:StyledLayerDescriptor version="1.0.0"
    xsi:schemaLocation="http://www.opengis.net/sld StyledLayerDescriptor.xsd"
    xmlns:sld="http://www.opengis.net/sld"
    xmlns:ogc="http://www.opengis.net/ogc"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <sld:NamedLayer>
    <sld:Name>Heatmap</sld:Name>
    <sld:UserStyle>
      <sld:Title>Heatmap</sld:Title>
      <sld:Abstract>A heatmap surface showing population density</sld:Abstract>
      <sld:FeatureTypeStyle>
        <sld:Transformation>
          <ogc:Function name="vec:Heatmap">
            <ogc:Function name="parameter">
              <ogc:Literal>data</ogc:Literal>
            </ogc:Function>
            <ogc:Function name="parameter">
              <ogc:Literal>weightAttr</ogc:Literal>
              <ogc:Literal>pop2000</ogc:Literal>
            </ogc:Function>
            <ogc:Function name="parameter">
              <ogc:Literal>radiusPixels</ogc:Literal>
              <ogc:Function name="env">
                <ogc:Literal>radius</ogc:Literal>
                <ogc:Literal>100</ogc:Literal>
              </ogc:Function>
            </ogc:Function>
            <ogc:Function name="parameter">
              <ogc:Literal>pixelsPerCell</ogc:Literal>
              <ogc:Literal>10</ogc:Literal>
            </ogc:Function>
            <ogc:Function name="parameter">
              <ogc:Literal>outputBBOX</ogc:Literal>
              <ogc:Function name="env">
                <ogc:Literal>wms_bbox</ogc:Literal>
              </ogc:Function>
            </ogc:Function>
            <ogc:Function name="parameter">
              <ogc:Literal>outputWidth</ogc:Literal>
              <ogc:Function name="env">
                <ogc:Literal>wms_width</ogc:Literal>
              </ogc:Function>
            </ogc:Function>
            <ogc:Function name="parameter">
              <ogc:Literal>outputHeight</ogc:Literal>
              <ogc:Function name="env">
                <ogc:Literal>wms_height</ogc:Literal>
              </ogc:Function>
            </ogc:Function>
          </ogc:Function>
        </sld:Transformation>
        <sld:Rule>
          <sld:RasterSymbolizer>
            <!-- specify geometry attribute to pass validation -->
            <sld:Geometry>
              <ogc:PropertyName>the_geom</ogc:PropertyName>
            </sld:Geometry>
            <sld:Opacity>0.6</sld:Opacity>
            <sld:ColorMap type="ramp">
              <sld:ColorMapEntry color="#BF00FF" quantity="-0.6" label="-0.6"/>
              <sld:ColorMapEntry color="#3F00FF" quantity="-0.45" label="-0.45"/>
              <sld:ColorMapEntry color="#003FFF" quantity="-0.3" label="-0.3" />
              <sld:ColorMapEntry color="#00BFFF" quantity="-0.15" label="-0.15" />
              <sld:ColorMapEntry color="#FFFFFF" quantity="-0.05" label="-0.05" />
              <sld:ColorMapEntry color="#D6D6D6" quantity="0.0" label="0.0" />
              <sld:ColorMapEntry color="#3FFF00" quantity="0.05" label="0.15"/>
              <sld:ColorMapEntry color="#BFFF00" quantity="0.15" label="0.3"/>
              <sld:ColorMapEntry color="#FFFF00" quantity="0.3" label="0.3"/>
              <sld:ColorMapEntry color="#FFBF00" quantity="0.45" label="0.45"/>
              <sld:ColorMapEntry color="#FF0000" quantity="0.6" label="0.6"/>
            </sld:ColorMap>
          </sld:RasterSymbolizer>
        </sld:Rule>
      </sld:FeatureTypeStyle>
    </sld:UserStyle>
  </sld:NamedLayer>
</sld:StyledLayerDescriptor>
"""

# Generate SLD body for the heatmap style
def generate_sld_body(color_range):
    sld_body = '<StyledLayerDescriptor version="1.0.0">\n'
    sld_body += '<NamedLayer>\n<Name>heatmap_style</Name>\n<UserStyle>\n'
    sld_body += '<FeatureTypeStyle>\n<Rules>\n'
    for i, color in enumerate(color_range):
        sld_body += f'<Rule>\n<PointSymbolizer>\n<Graphic>\n<Mark>\n<WellKnownName>circle</WellKnownName>\n'
        sld_body += f'<Fill><CssParameter name="fill">{color}</CssParameter></Fill>\n</Mark>\n'
        sld_body += '</Graphic>\n</PointSymbolizer>\n</Rule>\n'
    sld_body += '</Rules>\n</FeatureTypeStyle>\n</UserStyle>\n</NamedLayer>\n</StyledLayerDescriptor>'
    return sld_body

def get_url():
    geoserver_url = "http://localhost:8080/geoserver"
    workspace_name = "Test"
    layer_name = TABLE_NAME
    bbox = "xmin,ymin,xmax,ymax"
    width = 1024
    height = 768
    srs = "EPSG:4326"
    format = "image/png"

    # Final WMS URL
    wms_url = f"{geoserver_url}/wms?service=WMS&version=1.1.0&request=GetMap&layers=Test%3Amyapp_gispointmodel&styles=&bbox={bbox}&width={width}&height={height}&srs=EPSG%3A4326&format={format}"

    return wms_url

from scipy.interpolate import griddata
# from shapely.geometry import LineString
from django.contrib.gis.geos import GEOSGeometry
import matplotlib.pyplot as plt
from django.db import connection
# @api_view(['GET'])
def create_geo_tiff():
    points = fetch_points_data()
    x = points[:, 0]
    y = points[:, 1]
    elev = points[:, 2]

    # Define grid size and resolution
    x_min = min(x)
    x_max = max(x)
    y_min = min(y)
    y_max = max(y)

    x_res = 50  # Grid resolution in x-direction
    y_res = 50  # Grid resolution in y-direction

    # Create grid coordinates
    x_grid = np.linspace(x_min, x_max, x_res)
    y_grid = np.linspace(y_min, y_max, y_res)
    x_grid, y_grid = np.meshgrid(x_grid, y_grid)

    # Handle null elevation values
    null_elevation = 10000000000000000000
    points[:, 3] = np.where(np.isnan(points[:, 3]), null_elevation, points[:, 3])

    # Interpolate grid values using IDW
    grid_coords = np.array([x, y]).T
    z_grid = griddata(grid_coords, points[:, 3], (x_grid, y_grid), method='cubic', fill_value=null_elevation)

    # Flip the z_grid vertically to correct the orientation
    z_grid = np.flipud(z_grid)

    # Save the grid as GeoTIFF
    geotiff_path = os.path.abspath('points_grid.tif')
    save_as_geotiff(z_grid, geotiff_path, x_min, y_min, x_max, y_max)
    print(f"GeoTIFF saved at {geotiff_path}")

def save_as_geotiff(grid, filename, x_min, y_min, x_max, y_max):
    y_size, x_size = grid.shape
    driver = gdal.GetDriverByName('GTiff')
    dataset = driver.Create(filename, x_size, y_size, 1, gdal.GDT_Float32)

    # Set geotransform (top left x, w-e pixel resolution, rotation, top left y, rotation, n-s pixel resolution)
    x_res = (x_max - x_min) / float(x_size)
    y_res = (y_max - y_min) / float(y_size)
    geotransform = (x_min, x_res, 0, y_max, 0, -y_res)
    dataset.SetGeoTransform(geotransform)

    # Set spatial reference to EPSG:3857
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3857)
    dataset.SetProjection(srs.ExportToWkt())

    band = dataset.GetRasterBand(1)
    band.WriteArray(grid)
    band.FlushCache()

    # Verify if data is written correctly
    if band.ReadAsArray().shape != grid.shape:
        raise RuntimeError("Data writing issue: Shape mismatch")

    # Properly close the dataset
    dataset = None

def fetch_points_data():
    # Retrieve points data
    points_queryset = GISPointModel.objects.all()

    transformer = Transformer.from_crs("epsg:4326", "epsg:3857", always_xy=True)

    # Convert to list of tuples (x, y, elevation)
    points_list = [(*transformer.transform(point.geom.x, point.geom.y), float(point.grading), float(point.bottom_of_pile)) for point in points_queryset]

    # Convert to numpy array
    points = np.array(points_list)

    return points
# def create_geo_tiff():
#     points = fetch_points_data()
#     x = points[:, 0]
#     y = points[:, 1]
#     elev = points[:, 2]
#
#     # Define grid size and resolution
#     x_min = min(x)
#     x_max = max(x)
#     y_min = min(y)
#     y_max = max(y)
#
#     x_res = 40  # Grid resolution in x-direction
#     y_res = 40 # Grid resolution in y-direction
#
#     # Create empty grid
#     x_grid = np.linspace(x_min, x_max, x_res)
#     y_grid = np.linspace(y_min, y_max, y_res)
#     x_grid, y_grid = np.meshgrid(x_grid, y_grid)
#     z_grid = np.zeros_like(x_grid)
#
#     # Assign values to grid points based on the nearest input point
#     for lon, lat , value,bottomPile in points:
#         xi = np.argmin(np.abs(x_grid[0] - lon))
#         yi = np.argmin(np.abs(y_grid[:, 0] - lat))
#         z_grid[yi , xi] = bottomPile
#
#     # Flip the z_grid vertically to correct the orientation
#     z_grid = np.flipud(z_grid)
#     # Save the grid as GeoTIFF
#     geotiff_path = os.path.abspath('points_grid.tif')
#     save_as_geotiff(z_grid, geotiff_path, x_min, y_min, x_max, y_max)
#     print(f"GeoTIFF saved at {geotiff_path}")
#
# # Save the numpy array as a GeoTIFF
# def save_as_geotiff(grid, filename, x_min, y_min, x_max, y_max):
#     y_size, x_size = grid.shape
#     driver = gdal.GetDriverByName('GTiff')
#     dataset = driver.Create(filename, x_size, y_size, 1, gdal.GDT_Float32)
#
#     # Set geotransform (top left x, w-e pixel resolution, rotation, top left y, rotation, n-s pixel resolution)
#     x_res = (x_max - x_min) / float(x_size)
#     y_res = (y_max - y_min) / float(y_size)
#     geotransform = (x_min, x_res, 0, y_max, 0, -y_res)
#     dataset.SetGeoTransform(geotransform)
#
#     # Set spatial reference to EPSG:3857
#     srs = osr.SpatialReference()
#     srs.ImportFromEPSG(3857)
#     dataset.SetProjection(srs.ExportToWkt())
#
#     band = dataset.GetRasterBand(1)
#     band.WriteArray(grid)
#     band.FlushCache()
#
#     # Verify if data is written correctly
#     if band.ReadAsArray().shape != grid.shape:
#         raise RuntimeError("Data writing issue: Shape mismatch")
#
#     # Properly close the dataset
#     dataset = None

# def create_geo_tiff():
#     points = fetch_points_data()
#     x = points[:, 0]
#     y = points[:, 1]
#     elev = points[:, 2]
#
#     # Define grid size and resolution
#     x_min = min(x)
#     x_max = max(x)
#     y_min = min(y)
#     y_max = max(y)
#
#     x_res = 100  # Grid resolution in x-direction
#     y_res = 100  # Grid resolution in y-direction
#
#     # Create empty grid
#     x = np.linspace(x_min, x_max, x_res)
#     y = np.linspace(y_min, y_max, y_res)
#     x_grid, y_grid = np.meshgrid(x, y)
#     z_grid = np.zeros_like(x_grid)
#
#     # Assign values to grid points based on the nearest input point
#     for lon, lat, value in points:
#         xi = np.argmin(np.abs(x - lon))
#         yi = np.argmin(np.abs(y - lat))
#         z_grid[yi, xi] = value
#
#     # Save the grid as GeoTIFF
#     geotiff_path = os.path.abspath('points_grid.tif')
#     save_as_geotiff(z_grid, geotiff_path, x_min, y_min, x_max, y_max)
#     print(f"GeoTIFF saved at {geotiff_path}")
#
#  # Save the numpy array as a GeoTIFF
# def save_as_geotiff(grid, filename, x_min, y_min, x_max, y_max):
#     y_size, x_size = grid.shape
#     driver = gdal.GetDriverByName('GTiff')
#     dataset = driver.Create(filename, x_size, y_size, 1, gdal.GDT_Float32)
#
#     # Set geotransform (top left x, w-e pixel resolution, rotation, top left y, rotation, n-s pixel resolution)
#     x_res = (x_max - x_min) / float(x_size)
#     y_res = (y_max - y_min) / float(y_size)
#     geotransform = (x_min, x_res, 0, y_max, 0, -y_res)
#     dataset.SetGeoTransform(geotransform)
#
#     # Set spatial reference
#     srs = osr.SpatialReference()
#     srs.ImportFromEPSG(4326)  # WGS84
#     dataset.SetProjection(srs.ExportToWkt())
#
#     band = dataset.GetRasterBand(1)
#     band.WriteArray(grid)
#     band.FlushCache()
#
#     # Verify if data is written correctly
#     if band.ReadAsArray().shape != grid.shape:
#         raise RuntimeError("Data writing issue: Shape mismatch")
#
#     # Properly close the dataset
#     dataset = None

def create_contour_layer():
    points = fetch_points_data()
    contours, contour_levels = generate_contours(points)
    linestrings = contour_to_linestring(contours, contour_levels)
    save_contours_to_postgis(linestrings)

from pyproj import Transformer
# def fetch_points_data():
#     # Retrieve points data
#     points_queryset = GISPointModel.objects.all()
#
#     transformer = Transformer.from_crs("epsg:4326", "epsg:3857", always_xy=True)
#
#     # Convert to list of tuples (x, y, elevation)
#     points_list = [(*transformer.transform(point.geom.x, point.geom.y), float(point.grading),float(point.bottom_of_pile))  for point in points_queryset]
#
#     # Convert to numpy array
#     points = np.array(points_list)
#
#     return points

def generate_contours(points):
    x = points[:, 0]
    y = points[:, 1]
    elev = points[:, 2]

    # Define grid for interpolation
    grid_x, grid_y = np.mgrid[min(x):max(x):100j, min(y):max(y):100j]

    # Interpolate elevation data
    grid_z = griddata((x, y), elev, (grid_x, grid_y), method='linear', fill_value=0)

    # Replace nan values with 0
    grid_z = np.nan_to_num(grid_z, nan=0.0)

    # Generate contours
    contour_levels = np.linspace(np.min(elev), np.max(elev), num=10)
    contours = plt.contour(grid_x, grid_y, grid_z, levels=contour_levels)

    return contours, contour_levels

def contour_to_linestring(contour_paths, contour_levels):
    linestrings = []
    for i, collection in enumerate(contour_paths.collections):
        level = contour_levels[i]
        for path in collection.get_paths():
            v = path.vertices
            if len(v) > 1:  # Only consider valid paths
                linestring = LineString(v)
                linestrings.append((linestring, level))
    return linestrings

def save_contours_to_postgis(linestrings):
    contour_to_create = []
    for ls, level in linestrings:
        geom = ls
        contour = GISContour(grading=level, geom=geom)
        contour_to_create.append(contour)

    print('bulk adding')
    GISContour.objects.bulk_create(contour_to_create)

def publish_geotiff_layer(catalog,workspace):
    # Define the path to your GeoTIFF file
    geotiff_file = os.path.abspath('points_grid.tif')

    # Define the coverage store name
    coverage_store_name = 'geoserver_python_pile_tiff_layer'

    # Get the data store
    data_store = None
    try:
        data_store = catalog.get_store(coverage_store_name, workspace)
    except:
        pass

    if data_store is None:
        # Create the coverage store
        coverage_store = catalog.create_coveragestore(
            name=coverage_store_name,
            data=geotiff_file,
            workspace=workspace,
            overwrite=False
        )
    else:
        catalog.delete(data_store, purge=True, recurse=True)
        print(f"Data store '{DATASTORE_NAME}' deleted successfully.")
        # Create the coverage store
        coverage_store = catalog.create_coveragestore(
            name=coverage_store_name,
            data=geotiff_file,
            workspace=workspace,
            overwrite=False
        )

    # Check if the coverage store was created successfully
    # if coverage_store:
    #     print(f'Coverage store {coverage_store_name} created successfully.')
    # else:
    #     print('Failed to create coverage store.')

    # Publish the GeoTIFF as a coverage
    coverage_name = 'geoserver_python_pile_tiff_layer'
    print(f'Layer {coverage_name} published successfully.')
    # layer = catalog.publish_coverage(
    #     name=coverage_name,
    #     store=coverage_store,
    #     workspace=workspace,
    #     data=geotiff_file
    # )

    # Check if the layer was published successfully
    # if layer:
    #     print(f'Layer {coverage_name} published successfully.')
    # else:
    #     print('Failed to publish layer.')