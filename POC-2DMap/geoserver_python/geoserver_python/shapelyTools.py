import matplotlib.pyplot as plt
import matplotlib
import shapely

def shapelyDisp(sobj, **kwargs):
    plotObjs = []
    if hasattr(sobj,'geom_type'):
        if sobj.geom_type=='Point':
            # if marker is not included in kwargs, make it default to 'x'
            if 'marker' not in kwargs.keys():
                kwargs.update({'marker' : 'x'})
            x,y = sobj.xy
            return plt.plot(x,y,**kwargs)
        elif sobj.geom_type=='LineString':
            x,y = sobj.xy
            return plt.plot(x,y,**kwargs) #linestyle = linestyle)
        elif sobj.geom_type=='LinearRing':
            x,y = sobj.xy
            return plt.plot(x,y,**kwargs) #linestyle = linestyle)
        elif sobj.geom_type == 'Polygon':
            x,y = sobj.exterior.xy
            plotObjs.append(plt.plot(x,y,**kwargs)) #linestyle = linestyle)
            for interior in sobj.interiors:
                x,y = interior.xy
                plotObjs.append(plt.plot(x,y,**kwargs)) #linestyle = linestyle)
            return plotObjs
        elif sobj.geom_type=='MultiPoint':
            for obj in sobj:
                plotObjs.append(shapelyDisp(obj,**kwargs)) #linestyle = linestyle)
            return plotObjs
        elif sobj.geom_type=='MultiLineString':
            for obj in sobj:
                plotObjs.append(shapelyDisp(obj,**kwargs)) #linestyle = linestyle)
            return plotObjs
        elif sobj.geom_type=='MultiPolygon':
            for obj in sobj:
                plotObjs.append(shapelyDisp(obj,**kwargs)) #linestyle = linestyle)
            return plotObjs
        elif sobj.geom_type=='GeometryCollection':
            for obj in sobj.geoms:
                plotObjs.append(shapelyDisp(obj,**kwargs)) #linestyle = linestyle)
            return plotObjs
    elif len(sobj)>0:
        for obj in sobj:
            plotObjs.append(shapelyDisp(obj,**kwargs)) #linestyle = linestyle)
        return plotObjs
    elif sobj is []:
        return None
    else:
        print("could not plot %s"%type(sobj))
        return None

def shapelyRemove(pltObject):
    if isinstance(pltObject,matplotlib.lines.Line2D):
        plt.gca().lines.remove(pltObject)
    elif isinstance(pltObject,list):
        for k in pltObject:
            shapelyRemove(k)

        # if isinstance(k, list):
        #   try:
        #       plt.gca().lines.remove(k[0])
        #   except:
        #       pass
        # else:
        #   try:
        #       plt.gca().lines.remove(k)
        #   except:
        #       pass

