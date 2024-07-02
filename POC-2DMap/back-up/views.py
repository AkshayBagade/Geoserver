from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.contrib.gis.geos import Point
from .models import GISPointModel
from rest_framework.decorators import api_view
import json

@api_view(['POST'])
def upload_points(request):
    file = request.FILES.get('file')
    if not file:
        return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        # Process file in batches
        GISPointModel.objects.all().delete()
        batch_size = 1000  # Adjust batch size as needed
        points_data = []
        file =  pd.read_json(file)
        # trackers = file['Trackers'][:10]
        for line in file['Trackers']:
            try:
                points_data.append(line)
            except json.JSONDecodeError:
                pass

            if len(points_data) >= batch_size:
                process_batch(points_data)
                points_data = []

        # Process remaining points
        if points_data:
            process_batch(points_data)

        return Response({"message": "Points uploaded successfully"}, status=status.HTTP_201_CREATED)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def process_batch(points_data):
    points_to_create = []
    index = 0
    for point_data in points_data:
        for pile in point_data['piles']:
            name = 'P1' + str(index)
            longitude = pile['Position']['lon']
            latitude = pile['Position']['lat']
            grading = pile['Solution']['Grading']
            geom = Point(longitude, latitude)  # Creating a Point geometry
            print('adding')
            point_model = GISPointModel(name=name, geom=geom,grading=grading)
            points_to_create.append(point_model)
            index+=1

    print('bluk adding')
    GISPointModel.objects.bulk_create(points_to_create)


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
def get_points(request):
    # points = GISPointModel.objects.all()
    wmnsurl = None
    create_data_store()
    wmnsurl = publish_layer()
    # serializer = PointSerializer(points, many=True)
    return Response({'message':'Successfully Publish Point','url':'http://localhost:8080/geoserver/Test/wms'})

import requests

from geoserver.catalog import Catalog

# GeoServer details
GEOSERVER_URL = "http://localhost:8080/geoserver/rest/"
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
TABLE_NAME = "myapp_gispointmodel"

# GeoServer REST API endpoint URLs
# GEOSERVER_URL = 'http://localhost:8080/geoserver/rest'
# WORKSPACE = 'Test'
# DATASTORE_NAME = 'test123'
LAYER_NAME = 'point'

# GeoServer authentication credentials
GEOSERVER_USERNAME = 'admin'
GEOSERVER_PASSWORD = 'geoserver'

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

def create_data_store():
    DATASTORE_NAME = 'test_123'
    WORKSPACE = 'Test'
    catalog = Catalog(GEOSERVER_URL, username=USERNAME, password=PASSWORD_GEOSERVER)
    workspace = catalog.get_workspace(WORKSPACE)

    # Get the data store
    data_store = catalog.get_store(DATASTORE_NAME, workspace)

    if data_store is None:
        data_store = catalog.create_datastore(DATASTORE_NAME, workspace)
        data_store.connection_parameters.update(host="localhost", port="5432", database=DATABASE_NAME,
                                                user=DATABASE_USER, passwd=DATABASE_PASSWORD, dbtype="postgis",
                                                schema=SCHEMA)
        catalog.save(data_store)

        print('Data store created successfully')
    else:
        # Delete the data store
        catalog.delete(data_store, purge=True,recurse=True)
        print(f"Data store '{DATASTORE_NAME}' deleted successfully.")
        data_store = catalog.create_datastore(DATASTORE_NAME, workspace)
        data_store.connection_parameters.update(host="localhost", port="5432", database=DATABASE_NAME,
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
    style = catalog.get_style('New_heat')
    # catalog.create_style('heatmap_style_2', SLD_CONTENT)
    # print('Styled publish')

    # Publish layer with the heatmap style
    DATASTORE_NAME = 'test_123'
    data_store = catalog.get_store(DATASTORE_NAME, workspace)
    print(data_store.resource_url)
    layer = catalog.publish_featuretype(TABLE_NAME, data_store, native_crs="EPSG:4326", jdbc_virtual_table=None)
    # Apply the style to the published layer
    print('Style-----',style)
    layer.default_style = style
    catalog.save(layer)
    print('Successfully Publish Point')

# SLD content for the heat map style
SLD_CONTENT = """
<StyledLayerDescriptor version="1.0.0" xmlns="http://www.opengis.net/sld"
  xmlns:ogc="http://www.opengis.net/ogc" xmlns:xlink="http://www.w3.org/1999/xlink"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.opengis.net/sld
                      http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd">
  <NamedLayer>
    <Name>HeatMap</Name>
    <UserStyle>
      <Title>Heat Map Style</Title>
      <FeatureTypeStyle>
        <Rule>
          <ogc:Filter>
            <ogc:PropertyIsBetween>
              <ogc:PropertyName>Grading</ogc:PropertyName>
              <ogc:LowerBoundary>
                <ogc:Literal>0.1</ogc:Literal>
              </ogc:LowerBoundary>
              <ogc:UpperBoundary>
                <ogc:Literal>0.6</ogc:Literal>
              </ogc:UpperBoundary>
            </ogc:PropertyIsBetween>
          </ogc:Filter>
          <PointSymbolizer>
            <Graphic>
              <Mark>
                <WellKnownName>circle</WellKnownName>
                <Fill>
                  <CssParameter name="fill">#FF0000</CssParameter>
                </Fill>
              </Mark>
              <Size>
                <ogc:Div>
                  <ogc:PropertyName>Grading</ogc:PropertyName>
                  <ogc:Literal>10</ogc:Literal>
                </ogc:Div>
              </Size>
            </Graphic>
          </PointSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
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