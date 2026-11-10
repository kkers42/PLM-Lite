#include <cstdint>
#include <iostream>
#include <memory>

#include "oPRCFile.h"

int main(int argc, char **argv)
{
    if (argc != 2) return 1;
    uint32_t vertexCount = 0, triangleCount = 0;
    if (!(std::cin >> vertexCount >> triangleCount) ||
        !vertexCount || !triangleCount || vertexCount > 1000000 || triangleCount > 1000000)
        return 1;

    auto vertices = std::make_unique<double[][3]>(vertexCount);
    auto triangles = std::make_unique<uint32_t[][3]>(triangleCount);
    for (uint32_t i = 0; i < vertexCount; ++i)
        for (auto &coordinate : vertices[i])
            if (!(std::cin >> coordinate)) return 1;
    for (uint32_t i = 0; i < triangleCount; ++i)
        for (auto &index : triangles[i])
            if (!(std::cin >> index) || index >= vertexCount) return 1;

    oPRCFile file(argv[1]);
    const PRCmaterial material(RGBAColour(0.15, 0.2, 0.3),
                               RGBAColour(0.28, 0.52, 0.78),
                               RGBAColour(0, 0, 0),
                               RGBAColour(0.2, 0.2, 0.2), 1, 0.2);
    file.addTriangles(vertexCount, vertices.get(), triangleCount, triangles.get(),
                      material, 0, nullptr, nullptr, 0, nullptr, nullptr,
                      0, nullptr, nullptr, 0, nullptr, nullptr, 0);
    return file.finish() ? 0 : 1;
}
