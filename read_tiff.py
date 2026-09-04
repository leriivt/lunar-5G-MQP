import rasterio
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import LinearLocator

tiff = "Site01_final_adj_5mpp_surf.tif"
offset = 1737.4

with rasterio.open(tiff) as src:
    data = src.read(1)  # Read the first band
    transform = src.transform
    #width = src.width
    #height = src.height

    # Create pixel coordinate indices
    #rows, cols = np.indices(data.shape) #rows and cols are each 2d arrays
    rows = np.indices((src.width,))
    cols = np.indices((src.height,))

    # Convert pixel (col, row) coordinates to geospatial (X, Y) coordinates
    x, y = rasterio.transform.xy(transform, rows, cols)
    x = np.array(x) #1d arr
    y = np.array(y)
    X, Y = np.meshgrid(x, y) #turn each itso a 2d coord array

    print(data.shape)   # Dimensions (height, width)
    print(src.profile)  # Metadata
    print("\n")
    print(data)
    #print(src.crs)
    print("\n")


print(data) #data is a numpy array
print(transform)

Z = data 

fig, ax = plt.subplots(subplot_kw={"projection": "3d"})

surf = ax.plot_surface(X, Y, Z, cmap="viridis", linewidth=0, antialiased=False)

ax.zaxis.set_major_locator(LinearLocator(10))
# A StrMethodFormatter is used automatically
ax.zaxis.set_major_formatter('{x:.02f}')

# Add a color bar which maps values to colors.
fig.colorbar(surf, shrink=0.5, aspect=5)

plt.show()


